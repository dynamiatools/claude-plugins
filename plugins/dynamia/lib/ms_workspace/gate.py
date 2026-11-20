"""Pre-publish gate: scans what a batch is about to send for secrets, merge markers, oversized files and debug leftovers.

    ms-workspace gate [batch] [--json]

Only added lines are scanned. Findings that are never intended in a commit (secrets, private keys, merge markers, huge files)
block `ship`; debug leftovers are reported as warnings. A line containing `ms-gate: allow` is skipped.
"""
from __future__ import annotations

import fnmatch
import json
import math
import re
from pathlib import Path

from .core import Workspace, base_ref, batch_of_cwd, batch_repos, git, need_batch, toplevel, topo

PLACEHOLDER = re.compile(r"(changeme|change-me|example|placeholder|your[_-]|xxxx|dummy|sample|<[^>]+>|\$\{[^}]+\}|\{\{[^}]+\}\}|%\([^)]+\)s|\*{3,}|todo|redacted|fake|test)", re.I)
SECRET_PATTERNS = [
    ("aws-access-key", re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}\b|\bgithub_pat_[A-Za-z0-9_]{50,}\b")),
    ("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("stripe-live-key", re.compile(r"\b[sr]k_live_[0-9A-Za-z]{20,}\b")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY(?: BLOCK)?-----")),
    ("credentials-in-url", re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s/:@\"']{2,}:[^\s/@\"']{4,}@[^\s/\"']+", re.I)),
]
ASSIGNMENT = re.compile(r"""(?i)\b([\w.-]*(?:passw(?:or)?d|passwd|secret|api[_-]?key|access[_-]?key|auth[_-]?token|token|private[_-]?key)[\w.-]*)\s*[:=]\s*(["'])([^"'\s]{8,})\2""")
# Heuristics (not token formats) are the ones that raise false alarms, so they skip what is not a secret:
SQL_BEFORE = re.compile(r"(?i)\b(select|insert|update|delete|where|from|set|values|identified|alter|create|grant|join)\b[^\n]*$")
NAME_SUFFIX = re.compile(r"(?i)(column|field|name|header|label|type|path|prefix|suffix|storage|param|attr|attribute|prop|property|alias|var|env)$")
LOCAL_HOST = re.compile(r"(?i)@(localhost|127\.\d+\.\d+\.\d+|0\.0\.0\.0|\[::1\]|host\.docker\.internal|[\w.-]*\.(local|localhost|test|example|invalid))(?=[:/\s\"']|$)")
DEV_FILE = re.compile(r"(?i)(^|/)(docker-compose[^/]*\.ya?ml|compose[^/]*\.ya?ml|\.env\.(example|sample|dist|template)|[^/]*\.(example|sample|dist|template))$|(^|/)(src/test|testdata|fixtures?|seeds?)/")
JS, JVM, PY = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte"), (".java", ".kt", ".kts", ".groovy", ".scala"), (".py",)
# (rule, pattern, file extensions, noisy in test files). Rules only apply to the language they belong to.
DEBUG = [
    ("debugger", re.compile(r"^\s*debugger;?\s*$"), JS, False),
    ("focused-test", re.compile(r"\b(?:it|test|describe)\.only\(|\b(?:fit|fdescribe)\("), JS, False),
    ("console-log", re.compile(r"\bconsole\.(?:log|debug)\("), JS, True),
    ("print-stack-trace", re.compile(r"\.printStackTrace\(\)"), JVM, True),
    ("system-out", re.compile(r"\bSystem\.(?:out|err)\.print"), JVM, True),
    ("python-debugger", re.compile(r"^\s*(?:import pdb|pdb\.set_trace\(\)|breakpoint\(\))"), PY, False),
]
TEST_PATH = re.compile(r"(^|/)(tests?|__tests__|spec|e2e)/|\.(test|spec)\.[a-z]+$|(Test|Tests|IT)\.(java|kt)$|(^|/)test_[^/]*\.py$|_test\.(py|go)$")
IGNORE_FILES = ("*.lock", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "*.min.js", "*.min.css", "*.map", "*.svg", "gradle.lockfile")
MARKER_START = re.compile(r"^<{7}( |$)")
MARKER_END = re.compile(r"^>{7}( |$)")


def entropy(text: str) -> float:
    counts = {c: text.count(c) for c in set(text)}
    return -sum(n / len(text) * math.log2(n / len(text)) for n in counts.values())


def hide(value: str) -> str:
    return value[:4] + "***" + f"({len(value)} chars)" if len(value) > 8 else "***"


def scan_line(line: str, path: str) -> list[tuple[str, str, str]]:
    """Findings for one added line: (severity, rule, masked evidence)."""
    if "ms-gate: allow" in line:
        return []
    found = []
    for rule, rx in SECRET_PATTERNS:
        m = rx.search(line)
        if m and not (rule == "credentials-in-url" and (PLACEHOLDER.search(m.group(0)) or LOCAL_HOST.search(m.group(0)))):
            found.append(("block", rule, hide(m.group(0)) if rule != "private-key" else "-----BEGIN ... PRIVATE KEY-----"))
    m = ASSIGNMENT.search(line)
    if m and not found and not (SQL_BEFORE.search(line[:m.start()]) or NAME_SUFFIX.search(m.group(1)) or TEST_PATH.search(path) or DEV_FILE.search(path)):
        value = m.group(3)
        secretish = any(c.isdigit() for c in value) or (any(c.isupper() for c in value) and any(c.islower() for c in value))
        words = [w for w in re.split(r"[_.\-/ ]", value) if w]
        identifier = len(words) > 1 and all(w.islower() and w.isalpha() or re.fullmatch(r"v?\d{1,2}", w) for w in words)   # auth_token_v2_store
        if (secretish and not identifier and not PLACEHOLDER.search(value) and not PLACEHOLDER.search(m.group(1))
                and (entropy(value) >= 3.0 or len(value) >= 20 and not value.isalpha())):   # words with separators (json:access_token) are not secrets
            found.append(("block", "hardcoded-secret", f"{m.group(1)} = {hide(value)}"))
    for rule, rx, exts, noisy_in_tests in DEBUG:
        if path.endswith(exts) and rx.search(line) and not (noisy_in_tests and TEST_PATH.search(path)):
            found.append(("warn", rule, line.strip()[:60]))
            break
    return found


def parse_added(diff: str):
    """Yield (path, line_number, text) for every added line of a `git diff --unified=0`."""
    path, number = None, 0
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            path = raw[6:] if raw.startswith("+++ b/") else None
        elif raw.startswith("@@"):
            m = re.search(r"\+(\d+)", raw)
            number = int(m.group(1)) - 1 if m else 0
        elif raw.startswith("+") and path:
            number += 1
            yield path, number, raw[1:]


def scan_repo(directory: Path, base: str, max_kb: int, ignore: list[str], allow: list[re.Pattern]) -> list[dict]:
    findings = []
    ref = base_ref(directory, base)
    mb = git(directory, "merge-base", "HEAD", ref).stdout.strip() or ref
    diff = git(directory, "diff", "--unified=0", "--no-color", "--diff-filter=AM", mb).stdout
    added = list(parse_added(diff))
    for f in git(directory, "ls-files", "-o", "--exclude-standard").stdout.splitlines():   # untracked files count as fully added
        p = directory / f
        try:
            if p.stat().st_size <= max_kb * 1024 and b"\0" not in p.read_bytes()[:2048]:
                added += [(f, i, t) for i, t in enumerate(p.read_text(errors="replace").splitlines(), 1)]
        except OSError:
            pass
    seen_markers: dict[str, list] = {}
    for path, number, text in added:
        if any(fnmatch.fnmatch(path, g) or fnmatch.fnmatch(Path(path).name, g) for g in IGNORE_FILES + tuple(ignore)):
            continue
        if MARKER_START.match(text) or MARKER_END.match(text):
            seen_markers.setdefault(path, []).append((number, text[:7]))
        for severity, rule, evidence in scan_line(text, path):
            if any(rx.search(text) for rx in allow):
                continue
            findings.append({"severity": severity, "rule": rule, "path": path, "line": number, "evidence": evidence})
    for path, marks in seen_markers.items():
        starts, ends = [m for m in marks if m[1].startswith("<")], [m for m in marks if m[1].startswith(">")]
        if starts and ends:
            findings.append({"severity": "block", "rule": "merge-conflict-marker", "path": path, "line": starts[0][0], "evidence": "<<<<<<< ... >>>>>>>"})
    names = set(git(directory, "diff", "--name-only", "--diff-filter=AM", mb).stdout.splitlines()) | set(git(directory, "ls-files", "-o", "--exclude-standard").stdout.splitlines())
    for path in sorted(names):
        if any(fnmatch.fnmatch(path, g) or fnmatch.fnmatch(Path(path).name, g) for g in ignore):
            continue
        try:
            size = (directory / path).stat().st_size
        except OSError:
            continue
        if size > max_kb * 1024:
            findings.append({"severity": "block", "rule": "large-file", "path": path, "line": 0, "evidence": f"{size // 1024} KB (limit {max_kb} KB)"})
    return findings


def gate_batch(ws: Workspace, batch: str) -> dict[str, list[dict]]:
    return gate_places(ws, {r: (ws.batch_dir / batch / r, "") for r in batch_repos(ws, batch)})


def gate_places(ws: Workspace, place: dict) -> dict[str, list[dict]]:
    """Scan what each repo would send. `place` maps repo -> (checkout, branch), as ship builds it."""
    max_kb = int(ws.get("gate", "max_file_kb", default=1024))
    ignore = list(ws.get("gate", "ignore_paths", default=[]))
    allow = [re.compile(p) for p in ws.get("gate", "allow", default=[])]
    return {r: scan_repo(place[r][0], ws.base(r), max_kb, ignore, allow) for r in topo(ws, list(place))}


def report(results: dict[str, list[dict]], limit: int = 12) -> tuple[list[str], int, int]:
    lines, blocks, warns = [], 0, 0
    for repo, found in results.items():
        for f in found:
            blocks += f["severity"] == "block"
            warns += f["severity"] == "warn"
    shown = 0
    for repo, found in results.items():
        for f in sorted(found, key=lambda f: (f["severity"] != "block", f["path"], f["line"])):
            if shown < limit:
                where = f"{f['path']}:{f['line']}" if f["line"] else f["path"]
                lines.append(f"  {f['severity'].upper():<5} {repo}  {where}  {f['rule']}  {f['evidence']}")
            shown += 1
    if shown > limit:
        lines.append(f"  ... and {shown - limit} more")
    return lines, blocks, warns


def default_base(top: Path) -> str:
    """Base branch of a repo that is not part of a workspace: origin's default branch, else main/master/next/develop."""
    head = git(top, "symbolic-ref", "--short", "refs/remotes/origin/HEAD").stdout.strip().removeprefix("origin/")
    for cand in ([head] if head else []) + ["main", "master", "next", "develop"]:
        if git(top, "rev-parse", "--verify", "--quiet", cand).returncode == 0 or git(top, "rev-parse", "--verify", "--quiet", f"origin/{cand}").returncode == 0:
            return cand
    return "HEAD"


def cmd_gate(ws: Workspace | None, args: list[str]) -> int:
    as_json = "--json" in args
    names = [a for a in args if not a.startswith("-")]
    if names:
        if ws is None:
            die("a batch name needs a workspace; run it without arguments inside a repo to scan that repo")
        results = gate_batch(ws, need_batch(ws, names[0]))
    else:
        top = toplevel()
        if ws is not None and batch_of_cwd(ws):
            results = gate_batch(ws, batch_of_cwd(ws))
        else:
            get = (lambda *k, default=None: ws.get(*k, default=default)) if ws else (lambda *k, default=None: default)
            max_kb, ignore = int(get("gate", "max_file_kb", default=1024)), list(get("gate", "ignore_paths", default=[]))
            base = ws.base(top.name) if ws is not None and top.name in ws.repo_names() else default_base(top)
            results = {top.name: scan_repo(top, base, max_kb, ignore, [re.compile(p) for p in get("gate", "allow", default=[])])}
    lines, blocks, warns = report(results)
    if as_json:
        print(json.dumps({"blocking": blocks, "warnings": warns, "findings": results}, separators=(",", ":")))
    elif not blocks and not warns:
        print("gate: clean (no secrets, merge markers, oversized files or debug leftovers in what would be sent)")
    else:
        print(f"gate: {blocks} blocking, {warns} warning(s)")
        print("\n".join(lines))
        if blocks:
            print("Fix them, or mark a deliberate line with `ms-gate: allow` (or [gate] allow / ignore_paths in workspace.toml).")
    return 1 if blocks else 0
