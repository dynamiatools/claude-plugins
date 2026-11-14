"""PreToolUse hook: stop agents inside batch worktrees from publishing.

Three outcomes: allow, ask the user (pushing the batch's own work branch to origin, so work in progress is backed up
or shared without touching the base branch) and block (everything that publishes or destroys shared state).
It must fail closed: inside a batch a block never depends on parsing workspace.toml, "ask" is only reached for a plain
push of a non-protected work branch, and any internal error blocks a command that looks risky."""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys

from .core import batch_dirname, find_workspace_root

SEPARATORS = {"&&", "||", ";", "|", "&", "\n", "(", ")", "{", "}"}
WRAPPERS = {"sudo", "command", "exec", "nohup", "time", "env", "xargs", "nice", "stdbuf", "timeout", "rtk", "proxy"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
GIT_VALUE_OPTS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--super-prefix", "--config-env"}
PUBLISH_GH = {("pr", "create"), ("pr", "merge"), ("pr", "ready"), ("pr", "close"), ("release", "create"),
              ("repo", "create"), ("repo", "delete"), ("workflow", "run")}
LOOSE = re.compile(r"\bpush\b|\bgh\s+(pr|release|repo|api|workflow)\b|\bms-workspace\s+(clean|env|setup-hooks|undo|ps|docker)\b|\bsend-pack\b")
PUSH_VALUE_OPTS = {"-o", "--push-option", "--repo", "--receive-pack", "--exec"}
PUSH_BLOCK_OPTS = {"--force", "--delete", "--mirror", "--all", "--branches", "--prune", "--tags", "--atomic-all"}
ALWAYS_PROTECTED = {"main", "master", "qa", "prod", "production", "develop", "development", "staging", "next", "trunk", "HEAD"}
WORK_PREFIXES = ("int/", "agent/")   # integration branches of batches created before type-named branches
MESSAGE = ("Blocked: agents in a batch worktree must not push, open or merge PRs by hand, or run 'ms-workspace clean --force|undo|promote|setup-hooks|env --trust' "
           "or 'ship --skip-gate'. Commit locally. To back up or share work in progress, push the batch's own branch: "
           "'git push -u origin <branch>' (the user is asked to confirm; no force, never the base branch). "
           "When the user asks to publish or open a PR, use the /dynamia:ship skill: "
           "'ms-workspace ship <batch> [--pr] --yes' after showing the plan and getting their confirmation.")


HEREDOC = re.compile(r"<<-?[ \t]*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1([^\n]*)\n(.*?)\n[ \t]*\2[ \t]*(?=\n|$)", re.S)
SHELL_WORD = re.compile(r"(^|[\s;&|(/])(ba|z|da|k)?sh\b|\beval\b")


def strip_heredocs(command: str) -> str:
    """Drop the text of heredocs fed to a program that only reads it (python, cat, tee...): it is data, not commands, and
    words like 'git push' inside a script or a doc must not trip the guard. A heredoc fed to a shell is kept."""
    def drop(m: re.Match) -> str:
        head = command[command.rfind("\n", 0, m.start()) + 1:m.start()]
        return m.group(0) if SHELL_WORD.search(head) else f"<<{m.group(1)}{m.group(2)}{m.group(1)}{m.group(3)}\n{m.group(2)}"
    return HEREDOC.sub(drop, command)


def _segments(command: str) -> list[list[str]]:
    lex = shlex.shlex(command.replace("\n", " ; "), posix=True, punctuation_chars=";&|(){}")   # a newline ends a command like ";" does
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


class Ctx:
    """What a push decision may need from the worktree: its current branch and the branches nobody may push to by hand."""
    def __init__(self, branch: str = "", protected: set[str] | None = None):
        self.branch = branch
        self.protected = ALWAYS_PROTECTED | (protected or set())


def push_verdict(args: list[str], ctx: Ctx | None, trust_head: bool = True) -> str:
    """'ask' for a plain, non-forced push of a work branch to origin; '' (a block) for anything else."""
    if ctx is None:
        return ""
    positional, it = [], iter(args)
    for a in it:
        if a in PUSH_VALUE_OPTS:
            next(it, None)
        elif a.startswith("--"):
            if a.split("=")[0] in PUSH_BLOCK_OPTS or a.startswith("--force") or a.startswith("--delete") or a.startswith("--repo=") or a.startswith("--receive-pack="):
                return ""
        elif a.startswith("-") and len(a) > 1:
            if set(a[1:]) & {"f", "d"}:
                return ""
        else:
            positional.append(a)
    if len(positional) < 2:
        return ""   # a bare 'git push' or 'git push origin' relies on push.default: name the branch
    remote, refspecs = positional[0], positional[1:]
    if not remote or remote.startswith(("-", "+")) or "/" in remote or ":" in remote:
        return ""   # only a named remote (origin), never a URL or a path
    for spec in refspecs:
        if spec.startswith("+"):
            return ""
        src, colon, dst = spec.partition(":")
        if colon and not src:
            return ""   # ':branch' deletes it
        dst = dst if colon else src
        if dst.startswith("refs/heads/"):
            dst = dst[len("refs/heads/"):]
        if dst == "HEAD" and not colon:
            dst = ctx.branch if trust_head else ""
        if not dst or dst.startswith("refs/") or dst in ctx.protected or dst.startswith("release/"):
            return ""
        if dst != ctx.branch and not dst.startswith(WORK_PREFIXES):
            return ""
    return "ask"


def analyze(command: str, depth: int = 0, asks: list[str] | None = None, ctx: Ctx | None = None) -> str | None:
    """Return a reason when the command would publish or change shared state, else None.
    A push that is only worth confirming adds its description to `asks` instead."""
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
                inner = analyze(args[idx + 1], depth + 1, asks, ctx)
                if inner:
                    return inner
        elif prog == "eval" and depth < 3:
            inner = analyze(" ".join(args), depth + 1, asks, ctx)
            if inner:
                return inner
        elif prog == "git":
            sub, rest = _git_subcommand(args)
            if sub == "push" and asks is not None:
                before = args[:len(args) - len(rest) - 1]   # options given before 'push': -C <dir> and friends move HEAD elsewhere
                if push_verdict(rest, ctx, trust_head=not any(a.startswith(("-C", "--git-dir", "--work-tree")) for a in before)) == "ask":
                    asks.append("git push " + " ".join(rest))
                    continue
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
            if ((sub == "clean" and "--force" in args) or sub in ("setup-hooks", "undo", "promote") or (sub == "ship" and "--skip-gate" in args) or (sub == "env" and "--trust" in args)
                    or (sub == "ps" and words[1:2] == ["kill"]) or (sub == "docker" and words[1:2] == ["clean"])):
                return f"ms-workspace {sub}" + (" --force" if sub == "clean" else f" {words[1]}" if sub in ("ps", "docker") else " --skip-gate" if sub == "ship" else "")
    return None


def confirm_reasons(root, command: str) -> list[str]:
    """Commands that need the user's yes wherever they run: a ship that pushes straight to a base branch, and a forced clean.
    A ship that only opens PRs (`--pr`, or every repo of the batch has push = "pr") and a clean of a merged batch go through:
    the first is reversible, the second refuses by itself unless the work is already in the base branch."""
    out: list[str] = []
    try:
        segs = _segments(command)
    except ValueError:
        return out
    ws = None
    for seg in segs:
        seg = _strip(seg)
        if not seg or os.path.basename(seg[0]) != "ms-workspace":
            continue
        args = seg[1:]
        words = [a for a in args if not a.startswith("-")]
        sub = words[0] if words else ""
        if sub == "clean" and "--force" in args:
            out.append("clean --force discards a batch that is not merged")
        elif sub == "merge" and "--yes" in args:
            out.append("merge merges the pull request into the base branch")
        elif sub == "ship" and "--yes" in args:
            if "--pr" in args and "--direct" not in args:
                continue
            try:
                from .core import Workspace, batch_repos
                ws = ws or Workspace(root)
                if "--direct" in args:
                    raise ValueError("direct")
                if "--branch" in args:
                    repos = [words[1]] if len(words) > 1 else []
                else:
                    repos = batch_repos(ws, words[1]) if len(words) > 1 else []
                if not repos or any((ws.repo_cfg(r).get("push") or "direct") != "pr" for r in repos):
                    raise ValueError("direct")
            except Exception:
                out.append("ship pushes straight to the base branch (use --pr to open a pull request instead)")
    return out


def _ask(root, command: str, reason: str) -> None:
    _log(root, "ask", command)
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask", "permissionDecisionReason": reason}}))


def _log(root, outcome: str, command: str) -> None:
    try:
        from .core import Workspace
        Workspace(root).log("guard", outcome, "", "", command)
    except Exception:
        pass  # logging is best effort; the decision does not depend on the config being readable


def _log_blocked(root, command: str) -> None:
    _log(root, "blocked", command)


def _context(root) -> Ctx | None:
    """Current branch of the worktree the command runs in, and the base/release branches of the workspace.
    None (so a push stays blocked) outside a batch worktree or when git cannot say."""
    cwd = os.getcwd()
    if not any((cwd + "/").startswith(str(root / n) + "/") for n in {".batches", batch_dirname(root)}):
        return None
    try:
        out = subprocess.run(["git", "branch", "--show-current"], cwd=cwd, capture_output=True, text=True, timeout=3)
        branch = out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return None
    protected: set[str] = set()
    try:
        from .core import Workspace
        ws = Workspace(root)
        for r in ws.repo_names():
            protected.add(ws.base(r))
            protected.update(ws.repo_cfg(r).get("release") or [])
    except Exception:
        pass   # the built-in list of protected names still applies
    return Ctx(branch, protected)


THANOS_START = re.compile(r"\bms-workspace\s+thanos\s+(start|resume)\b")


def _thanos_step(command: str, sid: str) -> int | None:
    """During a THANOS mission the strict profile decides: block, approve without a prompt, or (None) leave it to the rest of the guard.
    It also tells the mission which session is starting it, because only a hook knows the session id."""
    try:
        from .thanos import bind_pending, session_mission
        if THANOS_START.search(command):
            bind_pending(sid)
        m = session_mission(sid)
        if not m:
            return None
        from .thanos_guard import verdict
        kind, why = verdict(command, m)
    except Exception:
        return None   # fail open here: the normal guard still applies
    if kind == "block":
        from pathlib import Path
        _log(Path(m["root"]), "blocked", f"{command}  [thanos: {why}]")
        print(f"THANOS blocked: {why}. Do not look for a way around it: record it with ms-workspace thanos block \"<what and why>\", "
              "park that task ([!] in THANOS.md) and continue with another one.", file=sys.stderr)
        return 2
    if kind == "allow":
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow",
                                                 "permissionDecisionReason": "THANOS: known-safe command inside the batch"}}))
        return 0
    return None


def cmd_guard() -> int:
    try:
        payload = json.loads(sys.stdin.read())
        command = payload["tool_input"]["command"]
        cwd = payload.get("cwd") or ""
    except (ValueError, KeyError, TypeError):
        return 0
    if not isinstance(command, str) or not command:
        return 0
    command = strip_heredocs(command)
    if cwd and os.path.isdir(cwd):
        os.chdir(cwd)
    decided = _thanos_step(command, payload.get("session_id") or "")
    if decided is not None:
        return decided
    root = find_workspace_root()
    if root is None:
        return 0
    names = {".batches", batch_dirname(root)}
    confirm = confirm_reasons(root, command)
    # Inside a batch, or reaching into one from elsewhere (`cd .batches/b/lib && git push`).
    if not (any((os.getcwd() + "/").startswith(str(root / n) + "/") for n in names) or any(n in command for n in names)):
        if confirm:
            _ask(root, command, "; ".join(confirm) + ".")
        return 0
    asks: list[str] = []
    try:
        reason = analyze(command, asks=asks, ctx=_context(root))
    except Exception:
        reason, asks = ("guard error" if LOOSE.search(command) else None), []  # fail closed on anything that looks risky
    if reason:
        _log_blocked(root, f"{command}  [{reason}]")
        print(MESSAGE, file=sys.stderr)
        return 2
    if asks or confirm:
        why = ["Push of a batch work branch to origin (" + "; ".join(asks) + "). Not the base branch, no force. Allow it to back up or share work in progress."] if asks else []
        _ask(root, command, " ".join(why + [c + "." for c in confirm]))
    return 0
