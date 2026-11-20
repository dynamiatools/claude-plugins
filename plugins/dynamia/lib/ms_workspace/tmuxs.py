"""tmux views: which sessions run, what one shows, and a line sent to one that is idle.

    ms-workspace tmux ls [--json]                      sessions with a guessed state (working, idle, needs-you, exited)
    ms-workspace tmux status <session> [--lines N]     the last lines of what the session shows
    ms-workspace tmux send <session> <text...> [--force]   type a line into the session; refused unless it is idle (--force overrides)

The state is read from the screen text, so it is a hint, not a fact: the screen of Claude Code can change between versions. Reading never
changes anything. Secrets that happen to be on the screen are masked. Nothing here creates or kills a session."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import time

from .core import die
from .gate import ASSIGNMENT, SECRET_PATTERNS

EXITED = re.compile(r"\[claude exited")
NEEDS_YOU = re.compile(r"Do you want to |\b1\. Yes\b|Allow this|\(y/n\)|Press Enter to continue", re.I)
WORKING = re.compile(r"esc to interrupt|ctrl\+c to interrupt", re.I)
PROMPT = re.compile(r"^[│|\s]*[❯>]\s*[│|]?\s*$")


def have_tmux() -> bool:
    return shutil.which("tmux") is not None


def tmux(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["tmux", *args], capture_output=True, text=True, timeout=10)


def target(name: str) -> str:
    return f"={name}:"   # `=` means an exact session name, never a prefix match


def mask(text: str) -> str:
    for _, rx in SECRET_PATTERNS:
        text = rx.sub("***", text)
    return ASSIGNMENT.sub(lambda m: m.group(0).replace(m.group(3), "***"), text)


def screen(name: str, lines: int = 40) -> str | None:
    """The last `lines` lines the session shows, masked; None when the session does not exist."""
    r = tmux("capture-pane", "-p", "-t", target(name), "-S", f"-{max(1, lines)}")
    if r.returncode != 0:
        return None
    rows = [x.rstrip() for x in r.stdout.splitlines()]
    while rows and not rows[-1]:
        rows.pop()
    return mask("\n".join(rows[-lines:]))


def classify(text: str) -> str:
    """working, needs-you, idle, exited or unknown, from the bottom of the screen."""
    tail = [x for x in text.splitlines() if x.strip()][-14:]
    joined = "\n".join(tail)
    if EXITED.search(joined):
        return "exited"
    if NEEDS_YOU.search(joined):
        return "needs-you"
    if WORKING.search(joined):
        return "working"
    if any(PROMPT.match(x) for x in tail[-6:]):
        return "idle"
    return "unknown"


def sessions() -> list[dict]:
    r = tmux("list-sessions", "-F", "#{session_name}\t#{session_created}\t#{session_attached}\t#{session_path}")
    if r.returncode != 0:
        return []   # no server running means no sessions
    out = []
    for line in r.stdout.splitlines():
        name, created, attached, path = (line.split("\t") + ["", "", "", ""])[:4]
        text = screen(name, 30) or ""
        out.append({"name": name, "age_min": max(0, int((time.time() - int(created or 0)) / 60)) if created.isdigit() else None,
                    "attached": int(attached or 0) if attached.isdigit() else 0, "path": path, "state": classify(text)})
    return out


def _need_tmux() -> None:
    if not have_tmux():
        die("tmux is not installed or not in PATH")


def _lines_opt(args: list[str], default: int) -> int:
    if "--lines" in args:
        i = args.index("--lines")
        try:
            return max(1, min(200, int(args[i + 1])))
        except (IndexError, ValueError):
            die("--lines needs a number")
    return default


def cmd_tmux(ws, args: list[str]) -> int:
    sub, rest = (args[0], args[1:]) if args else ("ls", [])
    _need_tmux()
    names = [a for i, a in enumerate(rest) if not a.startswith("-") and (i == 0 or rest[i - 1] != "--lines")]
    if sub == "ls":
        found = sessions()
        if "--json" in rest:
            print(json.dumps(found, separators=(",", ":")))
        elif not found:
            print("tmux: no sessions")
        else:
            for s in found:
                age = f"{s['age_min']}m" if s["age_min"] is not None else "?"
                print(f"{s['name']:<28} {s['state']:<10} {'attached' if s['attached'] else 'detached':<9} up {age:<6} {s['path']}")
        return 0
    if sub in ("status", "send"):
        if not names:
            die(f"usage: tmux {sub} <session>" + (" <text...> [--force]" if sub == "send" else " [--lines N]"))
        name = names[0]
        text = screen(name, _lines_opt(rest, 15 if sub == "status" else 30))
        if text is None:
            die(f"no tmux session named '{name}' (see: ms-workspace tmux ls)")
        state = classify(text)
        if sub == "status":
            print(f"{name}: {state}")
            print(text)
            return 0
        message = " ".join(names[1:])
        if not message:
            die("tmux send: nothing to send")
        if state != "idle" and "--force" not in rest:
            die(f"{name} is '{state}', not idle: typing now could land in the middle of something. Wait, answer it yourself, or pass --force")
        for part in (["send-keys", "-t", target(name), "-l", message], ["send-keys", "-t", target(name), "Enter"]):
            if tmux(*part).returncode != 0:
                die(f"could not type into {name}")
        print(f"sent to {name}: {message[:80]}")
        return 0
    die("usage: tmux ls [--json] | status <session> [--lines N] | send <session> <text...> [--force]")
