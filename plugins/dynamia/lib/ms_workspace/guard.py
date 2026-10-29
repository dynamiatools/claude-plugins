"""PreToolUse hook: stop agents inside batch worktrees from publishing.

It must fail closed: inside a batch the decision never depends on parsing workspace.toml, and any internal
error blocks a command that looks risky instead of letting it through."""
from __future__ import annotations

import json
import os
import re
import shlex
import sys

from .core import batch_dirname, find_workspace_root

SEPARATORS = {"&&", "||", ";", "|", "&", "\n", "(", ")", "{", "}"}
WRAPPERS = {"sudo", "command", "exec", "nohup", "time", "env", "xargs", "nice", "stdbuf", "timeout", "rtk", "proxy"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
GIT_VALUE_OPTS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--super-prefix", "--config-env"}
PUBLISH_GH = {("pr", "create"), ("pr", "merge"), ("pr", "ready"), ("pr", "close"), ("release", "create"),
              ("repo", "create"), ("repo", "delete"), ("workflow", "run")}
LOOSE = re.compile(r"\bpush\b|\bgh\s+(pr|release|repo|api|workflow)\b|\bms-workspace\s+(clean|env|setup-hooks|undo|ps|docker)\b|\bsend-pack\b")
MESSAGE = ("Blocked: agents in a batch worktree must not push, open or merge PRs by hand, or run 'ms-workspace clean|undo|promote|setup-hooks|env --trust' "
           "or 'ship --skip-gate'. Commit locally. When the user asks to publish or open a PR, use the /dynamia:ship skill: "
           "'ms-workspace ship <batch> [--pr] --yes' after showing the plan and getting their confirmation.")


def _segments(command: str) -> list[list[str]]:
    lex = shlex.shlex(command, posix=True, punctuation_chars=";&|(){}")
    lex.whitespace_split = True
    lex.commenters = ""
    tokens = list(lex)
    segs, cur = [], []
    for t in tokens:
        if t and set(t) <= set(";&|(){}") or t in SEPARATORS:
            if cur:
                segs.append(cur)
            cur = []
        else:
            cur.append(t)
    if cur:
        segs.append(cur)
    return segs


def _strip(seg: list[str]) -> list[str]:
    """Drop leading VAR=value assignments and wrapper commands so the real program comes first."""
    i = 0
    while i < len(seg):
        t = seg[i]
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", t) or os.path.basename(t) in WRAPPERS or (t.startswith("-") and i > 0):
            i += 1
        else:
            break
    return seg[i:]


def _git_subcommand(args: list[str]) -> tuple[str, list[str]]:
    i = 0
    while i < len(args):
        a = args[i]
        if not a.startswith("-"):
            return a, args[i + 1:]
        if a in GIT_VALUE_OPTS:
            i += 2
        else:
            i += 1  # -P, --no-pager, --git-dir=x, -C<path>, -cfoo=bar ...
    return "", []


def analyze(command: str, depth: int = 0) -> str | None:
    """Return a reason when the command would publish or change shared state, else None."""
    try:
        segs = _segments(command)
    except ValueError:
        return "unparseable command" if LOOSE.search(command) else None
    for seg in segs:
        seg = _strip(seg)
        if not seg:
            continue
        prog, args = os.path.basename(seg[0]), seg[1:]
        if prog in SHELLS and "-c" in args and depth < 3:
            idx = args.index("-c")
            if idx + 1 < len(args):
                inner = analyze(args[idx + 1], depth + 1)
                if inner:
                    return inner
        elif prog == "eval" and depth < 3:
            inner = analyze(" ".join(args), depth + 1)
            if inner:
                return inner
        elif prog == "git":
            sub, rest = _git_subcommand(args)
            if sub in ("push", "send-pack") or (sub == "subtree" and rest[:1] == ["push"]):
                return f"git {sub}"
        elif prog == "gh":
            words = [a for a in args if not a.startswith("-")]
            if tuple(words[:2]) in PUBLISH_GH:
                return "gh " + " ".join(words[:2])
            if words[:1] == ["api"] and any(a in ("-X", "--method", "-f", "-F", "--field", "--raw-field", "--input") or
                                            re.match(r"^-[fFX]", a) for a in args):
                return "gh api (write)"
        elif prog == "ms-workspace":
            sub = next((a for a in args if not a.startswith("-")), "")
            words = [a for a in args if not a.startswith("-")]
            if (sub in ("clean", "setup-hooks", "undo", "promote") or (sub == "ship" and "--skip-gate" in args) or (sub == "env" and "--trust" in args)
                    or (sub == "ps" and words[1:2] == ["kill"]) or (sub == "docker" and words[1:2] == ["clean"])):
                return f"ms-workspace {sub}" + (f" {words[1]}" if sub in ("ps", "docker") else " --skip-gate" if sub == "ship" else "")
    return None


def _log_blocked(root, command: str) -> None:
    try:
        from .core import Workspace
        Workspace(root).log("guard", "blocked", "", "", command)
    except Exception:
        pass  # logging is best effort; the block does not depend on the config being readable


def cmd_guard() -> int:
    try:
        payload = json.loads(sys.stdin.read())
        command = payload["tool_input"]["command"]
        cwd = payload.get("cwd") or ""
    except (ValueError, KeyError, TypeError):
        return 0
    if not isinstance(command, str) or not command:
        return 0
    if cwd and os.path.isdir(cwd):
        os.chdir(cwd)
    root = find_workspace_root()
    if root is None:
        return 0
    names = {".batches", batch_dirname(root)}
    # Inside a batch, or reaching into one from elsewhere (`cd .batches/b/lib && git push`).
    if not (any((os.getcwd() + "/").startswith(str(root / n) + "/") for n in names) or any(n in command for n in names)):
        return 0
    try:
        reason = analyze(command)
    except Exception:
        reason = "guard error" if LOOSE.search(command) else None  # fail closed on anything that looks risky
    if reason:
        _log_blocked(root, f"{command}  [{reason}]")
        print(MESSAGE, file=sys.stderr)
        return 2
    return 0
