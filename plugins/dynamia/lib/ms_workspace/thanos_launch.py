"""Run a THANOS mission in a session of its own, in tmux, so the current session stays free.

    ms-workspace thanos launch <batch> [--brief FILE | --goal T] [--max-steps N | --until-usage PCT] [--no-remote] [--yes]
    ms-workspace thanos sessions [--lines N] [--json]

`launch` needs the batch to exist (the skill opens it with `batch new`) and `--yes`: without it nothing starts and the plan is printed,
so a launch is always confirmed by a person first. It starts `thanos-<batch>` in tmux inside the batch's first repo worktree, runs
Claude Code there with `/dynamia:thanos --from-brief <brief>` and enables Remote Control. That session is a normal main session: it
claims the mission, the strict guard, the Stop hook, the cheap helpers and the Opus reviews all work as in any mission.
THANOS_CLAUDE_ARGS adds arguments to the `claude` command (a model, --plugin-dir). With no workspace the batch lives under
~/.dynamia/thanos/working-trees (see `thanos new`).
`sessions` lists the thanos-* tmux sessions with the mission summary and a guessed state; `needs-you` means a permission prompt waits."""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path

from .core import Workspace, batch_repos, die, need_batch
from .thanos import STATE, _load, _opt, _positional, _read, _summary
from .tmuxs import have_tmux, screen, sessions, target, tmux

BRIEF, LAUNCH = "THANOS-BRIEF.md", ".thanos-launch.json"


def session_name(batch: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_-]", "-", batch)
    return safe if safe.startswith("thanos-") else f"thanos-{safe}"


def _trust(directory: Path) -> None:
    """Let Claude Code skip its trust dialog for the worktree, the same way the tmux-session script does."""
    cfg = Path(os.path.expanduser("~/.claude.json"))
    try:
        real = cfg.resolve()
        data = json.loads(real.read_text())
        proj = data.setdefault("projects", {}).setdefault(str(directory), {})
        proj["hasTrustDialogAccepted"] = True
        fd, tmp = tempfile.mkstemp(dir=str(real.parent), prefix=".ms-", suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, real)
    except (OSError, ValueError):
        pass   # no config or not readable: Claude Code just shows its dialog


def _remote_control(session: str) -> None:
    """Once Claude shows its prompt, enable Remote Control so the session appears in claude.ai/code (best effort, in the background)."""
    s = shlex.quote(f"={session}:")
    script = (f"for i in $(seq 1 30); do sleep 1; tmux capture-pane -t {s} -p 2>/dev/null | grep -q '^❯' && break; done; "
              f"tmux send-keys -t {s} '/remote-control' Enter; sleep 1.5; tmux send-keys -t {s} Enter")
    subprocess.Popen(["bash", "-c", script], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def launch(ws: Workspace, args: list[str]) -> int:
    names = _positional(args)
    if not names:
        die("usage: thanos launch <batch> [--brief FILE | --goal TEXT] [--max-steps N | --until-usage PCT] [--no-remote] [--yes]")
    batch = need_batch(ws, names[0])
    bp = ws.batch_dir / batch
    repos = batch_repos(ws, batch)
    if not repos:
        die(f"{batch} has no repo worktree to start in")
    st = _read(bp / STATE)
    if st and st.get("status") == "working":
        die(f"{batch} already has a THANOS mission working: see 'ms-workspace thanos sessions'")
    session = session_name(batch)
    for tool in ("tmux", "claude"):
        if shutil.which(tool) is None:
            die(f"{tool} is not installed or not in PATH")
    if tmux("has-session", "-t", target(session)).returncode == 0:
        die(f"a tmux session named '{session}' already exists: attach with 'tmux attach -t {session}' or see 'ms-workspace thanos sessions'")
    brief_src, goal = _opt(args, "--brief", ""), _opt(args, "--goal", "")
    if not brief_src and not goal and not (bp / BRIEF).is_file():
        die(f"no brief: write {bp / BRIEF} (goal, success criteria, repos) or pass --brief FILE or --goal TEXT")
    cap = []
    if "--max-steps" in args:
        cap = ["--max-steps", str(_opt(args, "--max-steps", 0, int))]
    elif "--until-usage" in args:
        cap = ["--until-usage", str(_opt(args, "--until-usage", 0, float))]
    wt = bp / repos[0]
    prompt = " ".join(["/dynamia:thanos", "--from-brief", shlex.quote(str(bp / BRIEF))] + cap)
    print(f"THANOS launch plan: batch {batch}; tmux session {session}; starts in {wt}; brief {bp / BRIEF}"
          + (f"; cap {' '.join(cap)}" if cap else "") + "; Claude Code then runs the whole mission on its own")
    if "--yes" not in args:
        print("Nothing started. A person must confirm first; then run the same command with --yes.")
        return 1
    if brief_src:
        try:
            shutil.copyfile(brief_src, bp / BRIEF)
        except OSError as e:
            die(f"cannot read the brief: {e}")
    elif goal:
        (bp / BRIEF).write_text(f"# THANOS brief\n\n## Goal\n{goal}\n")
    _trust(wt)
    extra = " ".join(shlex.quote(a) for a in shlex.split(os.environ.get("THANOS_CLAUDE_ARGS", "")))   # e.g. --model or --plugin-dir
    inner = (f"claude {extra + ' ' if extra else ''}--name {shlex.quote(socket.gethostname() + ':' + session)} {shlex.quote(prompt)}; "
             f"printf '\\n[claude exited: press Enter to close]'; read _; tmux kill-session -t {shlex.quote(session)}")
    # The tmux server keeps the directory it starts in: start it in the workspace root, never in a batch worktree.
    ws.root.mkdir(parents=True, exist_ok=True)
    # -e: a tmux server that was already running has the PATH it started with; the session gets the one of whoever launches it.
    r = subprocess.run(["tmux", "new-session", "-d", "-s", session, "-n", session, "-c", str(wt), "-e", f"PATH={os.environ.get('PATH', '')}", inner],
                       cwd=str(ws.root), capture_output=True, text=True)
    if r.returncode != 0:
        die(f"tmux could not start the session: {(r.stderr or r.stdout).strip()[:200]}")
    if "--no-remote" not in args:
        _remote_control(session)
    (bp / LAUNCH).write_text(json.dumps({"session": session, "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "brief": str(bp / BRIEF)}))
    ws.log("thanos.launch", "ok", "", batch, session)
    print(f"started tmux session {session}. Follow it: ms-workspace thanos sessions | tmux attach -t {session} | claude.ai/code (Remote Control)")
    return 0


def _batch_of_session(ws: Workspace, session: str) -> Path | None:
    if not ws.batch_dir.is_dir():
        return None
    for d in ws.batch_dir.iterdir():
        info = _read(d / LAUNCH) if d.is_dir() else None
        if info and info.get("session") == session:
            return d
    return None


def list_sessions(ws: Workspace, args: list[str]) -> int:
    if not have_tmux():
        die("tmux is not installed or not in PATH")
    n = _opt(args, "--lines", 3, int)
    rows = []
    for s in sessions():
        if not s["name"].startswith("thanos-"):
            continue
        bp = _batch_of_session(ws, s["name"])
        mission = ""
        if bp and (bp / STATE).is_file():
            mission = _summary(_load(bp), bp)
        elif bp:
            mission = "no mission recorded yet (starting up)"
        rows.append({**s, "batch": bp.name if bp else "", "mission": mission, "screen": (screen(s["name"], n) if n else "") or ""})
    if "--json" in args:
        print(json.dumps(rows, separators=(",", ":")))
        return 0
    if not rows:
        print("no thanos-* tmux sessions")
        return 0
    for r in rows:
        print(f"{r['name']}  [{r['state']}]  {r['mission'] or 'not launched by thanos launch'}")
        if r["state"] == "needs-you":
            print(f"  needs you: a permission prompt waits. Answer it with 'tmux attach -t {r['name']}' or from Remote Control")
        if r["state"] == "exited":
            print("  the Claude Code process ended; the mission summary above is its last state")
        for line in r["screen"].splitlines():
            print(f"    | {line}")
    return 0
