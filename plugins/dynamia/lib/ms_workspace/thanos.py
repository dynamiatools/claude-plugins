"""THANOS: an autonomous mission inside its own batch worktree.

    ms-workspace thanos start <batch> [--goal T] [--max-steps N | --until-usage PCT] [--max-opus N] [--opus-used N] [--push-every N] [--deny-host H]
    ms-workspace thanos resume <batch>            re-attach this session to a mission that is still working
    ms-workspace thanos estimate <batch>          steps the task list in THANOS.md needs, and the cap that would be used
    ms-workspace thanos status [batch]            one line: status, steps, tasks, Opus reviews
    ms-workspace thanos task start|done <name>    a branch per task, merged into the batch branch when it is done
    ms-workspace thanos block [--task NAME] "<what and why>"   record something the guard refused (and park that task [!]), then move on
    ms-workspace thanos wait [MINUTES]            waiting for a background agent: the next stop is not counted as a step (plan usage is still enforced)
    ms-workspace thanos pause "<why>" | done [--force] | stop
    ms-workspace thanos panel [--session ID]      the mission and its THANOS.md as JSON, for the side panel (it never writes)
    ms-workspace thanos run [--name N] -- <cmd>   start a background process (dev server, watcher) the mission owns and may stop
    ms-workspace thanos procs | kill [NAME|PID|--all]   list or stop the processes started with `run` (they also stop on pause/done/stop)
    ms-workspace thanos unblock <task>            put a parked [!] task back to open once what blocked it is allowed
    ms-workspace thanos allow-suggest [--json]    permission rules for the commands the strict guard left to the normal prompt
    ms-workspace thanos extend <batch> --goal T [--check] [--skip-tests]   validate a finished mission, then start a new one on top of it
    ms-workspace thanos stop-hook | context       hooks (Stop, SessionStart)
    ms-workspace thanosguard                      hook (PreToolUse for Edit, Write and Agent)

State: <batch>/THANOS.md (the ledger the model keeps: goal, tasks `- [ ] [S|M|L] name`, decisions, failed attempts, blockers)
and <batch>/.thanos.json (counters and limits, written only by this tool). A pointer per session in the cache folder tells
the hooks which mission a session belongs to and feeds the status line badge.

A "step" is one autonomous turn: each time Claude would stop while tasks remain, the Stop hook counts one and asks it to
continue. The mission pauses on the step cap (or, with --until-usage, when plan usage reaches that percentage), on critical plan
usage, or after three steps without progress. """
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

from .core import Workspace, batch_repos, die, git, git_ok, git_out, need_batch
from .usage import cache_dir

UNTIL_USAGE_STEPS = 10000
MAX_WAITS = 30
DEFAULTS = {"max_steps": 30, "max_opus": 3, "push_every": 3, "stale_hours": 12}
SIZES = {"S": 2, "M": 4, "L": 8}
LEDGER, STATE = "THANOS.md", ".thanos.json"
REPORT, ASKED, LAST_BLOCK = "THANOS-REPORT.md", ".thanos-asked.jsonl", ".thanos-last-block.json"
OPUS_AGENTS = ("dynamia:boss", "boss")
TASK = re.compile(r"^\s*-\s*\[( |x|X|!)\]\s*(?:\[([SMLsml])\]\s*)?(.*)$")

TEMPLATE = """# THANOS mission: {batch}

Goal: {goal}

## Success criteria
- (each one must be checkable with a command or a file; list them before the first task)

## Tasks
<!-- `- [ ] [S|M|L] name: what`. [x] done, [!] parked because something was blocked. Keep names short, they become branch names. -->

## Decisions
<!-- what was chosen and why, so a resumed session does not redo it -->

## Failed attempts
<!-- what was tried and why it did not work: never repeat these -->

## Blockers
<!-- what the guard or a missing permission refused; each one is parked, not forced -->
"""


# ------------------------------------------------------------------------ state
def tdir() -> Path:
    p = cache_dir() / "thanos"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _read(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _write(path: Path, data) -> None:
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)


def _safe(sid: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "", sid or "")


def pointer_path(sid: str) -> Path:
    return tdir() / f"{_safe(sid)}.json"


def session_mission(sid: str, any_status: bool = False) -> dict | None:
    """The mission a session belongs to: its state plus batch_path and root. Strict rules apply only while it is `working`."""
    if not _safe(sid):
        return None
    ptr = _read(pointer_path(sid))
    if not ptr or not ptr.get("batch_path"):
        return None
    st = _read(Path(ptr["batch_path"]) / STATE)
    if not st:
        return None
    if not any_status and (st.get("status") != "working" or ptr.get("status") != "working"):
        return None
    if time.time() - ptr.get("touched", 0) > st.get("stale_hours", DEFAULTS["stale_hours"]) * 3600:
        return None
    return {**st, "batch_path": ptr["batch_path"], "root": ptr["root"], "sid": sid}


def _sync_pointers(batch_path: str, status: str, touch: bool = True) -> None:
    for f in tdir().glob("*.json"):
        ptr = _read(f)
        if ptr and ptr.get("batch_path") == batch_path:
            ptr["status"] = status
            if touch:
                ptr["touched"] = time.time()
            _write(f, ptr)


def bind_pending(sid: str) -> None:
    """Called by the guard right before `thanos start|resume` runs: only the hook knows the session id."""
    if _safe(sid):
        _write(tdir() / "pending.json", {"sid": sid, "ts": time.time()})


def _claim_session() -> str:
    path = tdir() / "pending.json"
    p = _read(path)
    path.unlink(missing_ok=True)
    return p["sid"] if p and time.time() - p.get("ts", 0) < 180 else ""


def _attach(sid: str, batch_path: Path, root: Path, status: str) -> None:
    if _safe(sid):
        _write(pointer_path(sid), {"batch_path": str(batch_path), "root": str(root), "status": status, "touched": time.time()})


def cfg(ws: Workspace, key: str):
    return ws.get("thanos", key, default=DEFAULTS[key])


# ----------------------------------------------------------------------- ledger
def ledger_path(batch_path: Path) -> Path:
    return batch_path / LEDGER


def tasks(batch_path: Path) -> list[dict]:
    try:
        lines = ledger_path(batch_path).read_text().splitlines()
    except OSError:
        return []
    out = []
    for n, line in enumerate(lines):
        m = TASK.match(line)
        if m:
            out.append({"line": n, "mark": m.group(1).lower(), "size": (m.group(2) or "").upper(), "text": m.group(3).strip()})
    return out


def estimate(batch_path: Path) -> tuple[int, int]:
    """(steps, tasks) for the tasks still open: S=2, M=4, L=8 steps (3 when unsized) plus 30 % margin."""
    todo = [t for t in tasks(batch_path) if t["mark"] == " "]
    raw = sum(SIZES.get(t["size"], 3) for t in todo)
    return (raw * 13 + 9) // 10, len(todo)


def _mark_done(batch_path: Path, name: str) -> bool:
    path = ledger_path(batch_path)
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return False
    for t in tasks(batch_path):
        if t["mark"] == " " and re.match(rf"^{re.escape(name)}(?![\w-])", t["text"]):
            lines[t["line"]] = lines[t["line"]].replace("[ ]", "[x]", 1)
            path.write_text("\n".join(lines) + "\n")
            return True
    return False


def _append_section(batch_path: Path, section: str, line: str) -> None:
    path = ledger_path(batch_path)
    text = path.read_text() if path.is_file() else ""
    if f"## {section}" not in text:
        text += f"\n## {section}\n"
    head, _, tail = text.partition(f"## {section}")
    body, sep, rest = tail.partition("\n## ")
    text = head + f"## {section}" + body.rstrip("\n") + f"\n{line}\n" + (("\n## " + rest) if sep else "")
    path.write_text(text)


def _signature(ws: Workspace, batch: str, batch_path: Path) -> str:
    h = hashlib.sha1()
    for t in tasks(batch_path):
        h.update(f"{t['mark']}{t['text']}".encode())
    notes = ledger_sections(batch_path)
    for key in ("failed", "decisions", "blockers"):   # a new failed attempt or decision is progress even without a commit
        h.update(f"{key}{len(notes[key])}".encode())
    for r in batch_repos(ws, batch):
        h.update(git_out(batch_path / r, "rev-parse", "HEAD").encode())
        h.update(git_out(batch_path / r, "status", "--porcelain").encode())
    return h.hexdigest()


def _batch_path(ws: Workspace, batch: str) -> Path:
    return ws.batch_dir / need_batch(ws, batch)


def _load(batch_path: Path) -> dict:
    st = _read(batch_path / STATE)
    if not st:
        die(f"no THANOS mission in {batch_path.name}: start one with 'ms-workspace thanos start {batch_path.name}'")
    return st


def _save(batch_path: Path, st: dict) -> None:
    _write(batch_path / STATE, st)


def _opt(args: list[str], flag: str, default=None, cast=str):
    if flag in args:
        i = args.index(flag)
        if i + 1 >= len(args):
            die(f"{flag} needs a value")
        try:
            return cast(args[i + 1])
        except ValueError:
            die(f"{flag}: invalid value '{args[i + 1]}'")
    return default


def _summary(st: dict, batch_path: Path) -> str:
    ts = tasks(batch_path)
    done, todo, parked = (sum(1 for t in ts if t["mark"] == k) for k in ("x", " ", "!"))
    return (f"THANOS {st['status']}: step {st['steps']}/{st['max_steps']}, tasks {done} done / {todo} open / {parked} parked, "
            f"Opus {st['opus_used']}/{st['max_opus']}, branch {st['branch']}")


# --------------------------------------------------------------------- commands
def cmd_thanos(ws: Workspace | None, args: list[str]) -> int:
    sub, rest = (args[0], args[1:]) if args else ("", [])
    if sub == "stop-hook":
        return hook_stop()
    if sub == "context":
        return hook_context()
    if sub == "panel":
        return cmd_panel(rest)
    if sub in ("procs", "kill"):
        return (_procs if sub == "procs" else _kill_cmd)(ws, rest)
    if ws is None:
        die("THANOS needs a workspace (run the dynamia:workspace-init skill first)")
    handler = {"start": _start, "resume": _resume, "estimate": _estimate, "status": _status, "task": _task, "block": _block,
               "wait": _wait, "pause": _pause, "done": _done, "stop": _stop, "run": _run, "unblock": _unblock,
               "allow-suggest": _allow_suggest, "extend": _extend}.get(sub)
    if handler is None:
        die("usage: thanos start|resume|extend|estimate|status|task|block|unblock|wait|run|procs|kill|allow-suggest|pause|done|stop|panel (see ms-workspace help)")
    return handler(ws, rest)


VALUE_FLAGS = {"--session", "--name", "--goal", "--max-steps", "--max-opus", "--opus-used", "--until-usage", "--push-every", "--deny-host", "--task"}


def num_str(x: float) -> str:
    return str(int(x)) if float(x) == int(x) else str(x)


def _positional(args: list[str]) -> list[str]:
    out, skip = [], False
    for a in args:
        if skip:
            skip = False
        elif a in VALUE_FLAGS:
            skip = True
        elif not a.startswith("-"):
            out.append(a)
    return out


def _find_batch(ws: Workspace, rest: list[str]) -> Path:
    """The batch named in the arguments, else the one the current directory belongs to."""
    from .core import batch_of_cwd
    names = _positional(rest)
    return _batch_path(ws, names[0] if names else batch_of_cwd(ws))


def _start(ws: Workspace, args: list[str], extra: dict | None = None) -> int:
    names = _positional(args)
    if not names:
        die("usage: thanos start <batch> [--goal TEXT] [--max-steps N] [--max-opus N] [--push-every N] [--deny-host HOST]")
    batch = need_batch(ws, names[0])
    bp = ws.batch_dir / batch
    repos = batch_repos(ws, batch)
    if not repos:
        die(f"batch '{batch}' has no repositories")
    if (bp / STATE).is_file() and (_read(bp / STATE) or {}).get("status") == "working":
        die(f"a mission is already working in '{batch}': use 'thanos resume {batch}' or 'thanos stop'")
    from .batches import int_branch
    goal = _opt(args, "--goal", "(write the goal here)")
    steps_est, n_tasks = estimate(bp)
    until = _opt(args, "--until-usage", 0, float)
    if until and not 1 <= until <= 100:
        die("--until-usage is a plan usage percentage between 1 and 100")
    # With a usage ceiling the step cap only guards against a runaway loop: the usage percentage is the real limit.
    max_steps = _opt(args, "--max-steps", UNTIL_USAGE_STEPS if until else cfg(ws, "max_steps"), int)
    max_opus = _opt(args, "--max-opus", cfg(ws, "max_opus"), int)
    opus_used = _opt(args, "--opus-used", 0, int)
    if max_steps < 1 or max_opus < 0 or not 0 <= opus_used <= max_opus:
        die("--max-steps must be at least 1, --max-opus 0 or more and --opus-used between 0 and --max-opus")
    deny = [args[i + 1] for i, a in enumerate(args) if a == "--deny-host" and i + 1 < len(args)] + list(ws.get("thanos", "deny_hosts", default=[]))
    st = {"batch": batch, "branch": int_branch(ws, batch, repos[0]), "goal": goal, "status": "working", "started": int(time.time()),
          "steps": 0, "max_steps": max_steps, "opus_used": opus_used, "max_opus": max_opus, "until_usage": until, "push_every": _opt(args, "--push-every", cfg(ws, "push_every"), int),
          "tasks_done": 0, "stalls": 0, "signature": "", "deny_hosts": deny, "stale_hours": cfg(ws, "stale_hours"), "blockers": 0, "generation": 1, "procs": [], **(extra or {})}
    _save(bp, st)
    if not ledger_path(bp).is_file():
        ledger_path(bp).write_text(TEMPLATE.format(batch=batch, goal=goal))
    sid = _claim_session()
    _attach(sid, bp, ws.root, "working")
    ws.log("thanos.start", "ok", "", batch, f"max_steps={max_steps} max_opus={max_opus}")
    print(f"THANOS mission started in {bp}")
    print(f"  cap: {'plan usage ' + num_str(until) + '%' if until else str(max_steps) + ' steps'}, {max_opus} Opus reviews ({opus_used} already used), "
          f"push of the batch branch every {st['push_every'] or 'never'} task(s)")
    if n_tasks and not until and steps_est > max_steps:
        print(f"  warning: the open tasks are estimated at {steps_est} steps, above the cap of {max_steps}; raise it with --max-steps or trim the plan")
    if not sid:
        print("  note: this session could not be linked (no hook saw the start): the strict guard and the status badge need the hooks installed")
    return 0


def _resume(ws: Workspace, args: list[str]) -> int:
    bp = _find_batch(ws, args)
    st = _load(bp)
    if st["status"] == "done":
        die("this mission is done")
    st["status"], st["stalls"] = "working", 0
    _save(bp, st)
    _attach(_claim_session(), bp, ws.root, "working")
    _sync_pointers(str(bp), "working")
    ws.log("thanos.resume", "ok", "", st["batch"], f"step {st['steps']}")
    print(_summary(st, bp))
    print("\n".join(_where(ws, st)))
    return 0


def _estimate(ws: Workspace, args: list[str]) -> int:
    bp = _find_batch(ws, args)
    steps, n = estimate(bp)
    cap = (_read(bp / STATE) or {}).get("max_steps", cfg(ws, "max_steps"))
    print(f"{n} open task(s): about {steps} steps (S=2, M=4, L=8, unsized=3, plus 30% margin). Cap that would apply: {cap}.")
    if steps > cap:
        print(f"The estimate is above the cap: pass --max-steps {steps} to start, or split the plan.")
    return 0


def _status(ws: Workspace, args: list[str]) -> int:
    bp = _find_batch(ws, args)
    print(_summary(_load(bp), bp))
    return 0


def _repo_dirs(ws: Workspace, st: dict) -> list[tuple[str, Path]]:
    return [(r, ws.batch_dir / st["batch"] / r) for r in batch_repos(ws, st["batch"])]


def _where(ws: Workspace, st: dict) -> list[str]:
    """Where each worktree stands: its branch and uncommitted files; names the task that was interrupted, if any."""
    lines, prefix, task = [], f"agent/{st['batch']}/", ""
    for r, wt in _repo_dirs(ws, st):
        cur, dirty = git(wt, "branch", "--show-current"), git(wt, "status", "--porcelain")
        branch = cur.stdout.strip() if cur.returncode == 0 else "?"
        n = len([x for x in dirty.stdout.splitlines() if x.strip()]) if dirty.returncode == 0 else 0
        lines.append(f"  {r}: on {branch}" + (f", {n} uncommitted file(s)" if n else ""))
        if branch.startswith(prefix):
            task = branch[len(prefix):]
    if task:
        lines.append(f"  interrupted task: {task}. Read its commits and diff, finish it, ms-workspace test t0, then: ms-workspace thanos task done {task}")
    return lines


def _task(ws: Workspace, args: list[str]) -> int:
    if len(args) < 2 or args[0] not in ("start", "done"):
        die("usage: thanos task start|done <name>")
    action, name = args[0], args[1]
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*$", name):
        die(f"invalid task name '{name}': letters, digits, '.', '_' and '-'")
    bp = _find_batch(ws, args[2:])
    st = _load(bp)
    branch, tbranch = st["branch"], f"agent/{st['batch']}/{name}"
    dirs = _repo_dirs(ws, st)
    if action == "start":
        for r, wt in dirs:
            cur = git_out(wt, "branch", "--show-current")
            if cur != branch:
                die(f"{r}: the worktree is on '{cur}'; finish or abandon that task first (the batch branch is {branch})")
            if git_out(wt, "status", "--porcelain"):
                die(f"{r}: uncommitted changes on {branch}; commit them before starting a task")
        for r, wt in dirs:
            res = git(wt, "switch", "-c", tbranch)
            if res.returncode != 0:
                die(f"{r}: could not create {tbranch}: {res.stderr.strip()}")
        ws.log("thanos.task", "ok", "", st["batch"], f"start {name}")
        print(f"task {name}: on {tbranch} in {', '.join(r for r, _ in dirs)}")
        return 0
    merged = []
    for r, wt in dirs:
        if git_out(wt, "branch", "--show-current") != tbranch:
            die(f"{r}: not on {tbranch}; run 'thanos task start {name}' first")
        if git_out(wt, "status", "--porcelain"):
            die(f"{r}: uncommitted changes on {tbranch}; commit them first")
    for r, wt in dirs:
        ahead = git_out(wt, "rev-list", "--count", f"{branch}..{tbranch}")
        git(wt, "switch", branch)
        if ahead == "0":
            git(wt, "branch", "-d", tbranch)
            continue
        res = git(wt, "merge", "--no-ff", "--no-edit", "-m", f"Integrate task {name}", tbranch)
        if res.returncode != 0:
            git(wt, "merge", "--abort")
            git(wt, "switch", tbranch)
            ws.log("thanos.task", "conflict", r, st["batch"], name)
            die(f"{r}: merging {tbranch} into {branch} conflicts; you are back on {tbranch}: rebase it on {branch} (git rebase {branch}), fix, and run 'thanos task done {name}' again")
        merged.append(r)
    ledger_ok = _mark_done(bp, name)
    st["tasks_done"] += 1
    _save(bp, st)
    ws.log("thanos.task", "ok", "", st["batch"], f"done {name}")
    print(f"task {name}: merged into {branch}" + (f" ({', '.join(merged)})" if merged else " (no changes)") + ("" if ledger_ok else "; no open line for it in THANOS.md"))
    every = st.get("push_every") or 0
    if every and st["tasks_done"] % every == 0:
        for r, wt in dirs:
            res = git(wt, "push", "-u", "origin", branch)
            ws.log("thanos.push", "ok" if res.returncode == 0 else "fail", r, st["batch"], branch)
            print(f"  backup push of {branch} ({r}): " + ("ok" if res.returncode == 0 else "failed, continuing (" + res.stderr.strip().splitlines()[-1][:80] + ")" if res.stderr.strip() else "failed, continuing"))
    return 0


def _park(batch_path: Path, name: str) -> bool:
    """Mark the open task `name` as parked ([!]) in the ledger."""
    path = ledger_path(batch_path)
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return False
    for t in tasks(batch_path):
        if t["mark"] == " " and re.match(rf"^{re.escape(name)}(?![\w-])", t["text"]):
            lines[t["line"]] = lines[t["line"]].replace("[ ]", "[!]", 1)
            path.write_text("\n".join(lines) + "\n")
            return True
    return False


def _block(ws: Workspace, args: list[str]) -> int:
    task = _opt(args, "--task", "")
    words, skip = [], False
    for a in args:
        if skip:
            skip = False
        elif a == "--task":
            skip = True
        else:
            words.append(a)
    text = " ".join(words).strip()
    if not text:
        die('usage: thanos block [--task NAME] "<what was refused and why>"')
    bp = _find_batch(ws, [])
    st = _load(bp)
    st["blockers"] += 1
    _save(bp, st)
    _append_section(bp, "Blockers", f"- {time.strftime('%H:%M')} {text}")
    ws.log("thanos.block", "ok", "", st["batch"], text[:120])
    if task:
        print(f"recorded; task {task} parked [!]" if _park(bp, task) else f"recorded; no open task named {task} in THANOS.md to park")
    else:
        print("recorded; park the task with 'thanos block --task NAME ...' (or mark it [!]) and continue with another one")
    return 0


def _wait(ws: Workspace, args: list[str]) -> int:
    """Tell the Stop hook that Claude is only waiting for a background agent: stops are not steps until the time is up."""
    bp = _find_batch(ws, [])
    st = _load(bp)
    try:
        minutes = float(_positional(args)[0]) if _positional(args) else 10.0
    except ValueError:
        die("usage: thanos wait [MINUTES]")
    minutes = max(1.0, min(minutes, 60.0))
    st["waits"] = st.get("waits", 0) + 1
    if st["waits"] > MAX_WAITS:
        die(f"thanos wait was used {MAX_WAITS} times in this mission: a mission that keeps waiting is not making progress; finish, pause or stop it")
    st["waiting_until"] = time.time() + minutes * 60
    _save(bp, st)
    print(f"waiting for a background agent for up to {num_str(minutes)} minute(s): your next stop does not count as a step ({st['waits']}/{MAX_WAITS} waits used). End your turn; its notification will wake you.")
    return 0


def _finish(ws: Workspace, bp: Path, st: dict, status: str, why: str) -> None:
    stopped = _stop_procs(st)
    if stopped:
        why += f" ({stopped} background process(es) stopped)"
    st["status"] = status
    _save(bp, st)
    _sync_pointers(str(bp), status)
    try:
        from .handoff import write
        write(ws, st["batch"], force=True)
    except Exception:
        pass
    ws.log(f"thanos.{status}", "ok", "", st["batch"], why[:120])


def _pause(ws: Workspace, args: list[str]) -> int:
    bp = _find_batch(ws, [])
    st = _load(bp)
    _finish(ws, bp, st, "paused", " ".join(args) or "paused by request")
    print(_summary(st, bp))
    return 0


def _done(ws: Workspace, args: list[str]) -> int:
    bp = _find_batch(ws, [])
    st = _load(bp)
    open_tasks = [t["text"] for t in tasks(bp) if t["mark"] == " "]
    if open_tasks and "--force" not in args:
        die(f"{len(open_tasks)} task(s) still open (first: {open_tasks[0][:60]}); finish or park them, or pass --force")
    _report(ws, bp, st)
    _finish(ws, bp, st, "done", "mission finished")
    print(_summary(st, bp))
    print(f"report: {bp / REPORT}")
    print(f"Next for you: ms-workspace integrate / test t1 / plan {st['batch']}, then /dynamia:ship. THANOS never ships.")
    return 0


def drop_pointers(batch_path: str) -> None:
    for f in tdir().glob("*.json"):
        ptr = _read(f)
        if ptr and ptr.get("batch_path") == batch_path:
            f.unlink(missing_ok=True)


def _stop(ws: Workspace, args: list[str]) -> int:
    bp = _find_batch(ws, [])
    st = _load(bp)
    _finish(ws, bp, st, "paused", "stopped by the user")
    drop_pointers(str(bp))
    print("mission stopped; the ledger and the batch stay as they are")
    return 0


# ------------------------------------------------------- background processes
RUNNABLE = {"pnpm", "npm", "yarn", "bun", "npx", "node", "java", "python", "python3", "uvicorn", "gunicorn", "flask", "vite", "nuxt", "next"}


def _pick(ws: Workspace | None, args: list[str]) -> Path:
    """The mission's batch: the session named by --session (what the side panel passes), else the batch of the current directory."""
    sid = _opt(args, "--session", "")
    if sid:
        ptr = _read(pointer_path(sid)) if _safe(sid) else None
        if not ptr or not ptr.get("batch_path"):
            die("no THANOS mission for that session")
        return Path(ptr["batch_path"])
    if ws is None:
        die("THANOS needs a workspace (run the dynamia:workspace-init skill first) or --session ID")
    return _find_batch(ws, [])


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
        return True
    except OSError:
        return False


def _is_ours(p: dict) -> bool:
    """Guards against a reused pid: a live group leader must still be the command that was recorded."""
    try:
        cmd = Path(f"/proc/{p['pgid']}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
    except OSError:
        return True   # no leader any more: whatever still holds the group is its survivors
    return p["cmd"][:40] in cmd


def _stop_proc(p: dict) -> bool:
    if not _group_alive(p["pgid"]) or not _is_ours(p):
        return True
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(p["pgid"], sig)
        except OSError:
            return True
        for _ in range(30):
            time.sleep(0.1)
            if not _group_alive(p["pgid"]):
                return True
    return not _group_alive(p["pgid"])


def _stop_procs(st: dict) -> int:
    n = 0
    for p in st.get("procs") or []:
        n += 1 if _group_alive(p["pgid"]) and _stop_proc(p) else 0
    st["procs"] = []
    return n


def _run(ws: Workspace, args: list[str]) -> int:
    if "--" not in args or not args[args.index("--") + 1:]:
        die("usage: thanos run [--name NAME] -- <command>")
    i = args.index("--")
    flags, cmd = args[:i], args[i + 1:]
    text = cmd[0] if len(cmd) == 1 else shlex.join(cmd)
    bp = _find_batch(ws, [])
    st = _load(bp)
    if st["status"] != "working":
        die(f"the mission is {st['status']}: resume it first")
    from .thanos_guard import inside, verdict
    m = {**st, "batch_path": str(bp), "root": str(ws.root)}
    cwd = os.getcwd() if inside(os.getcwd(), m, os.getcwd()) else str(bp)
    kind, why = verdict(text, m, cwd=cwd)
    prog = os.path.basename(shlex.split(text)[0]) if text.strip() else ""
    if "$(" in text or "`" in text or kind == "block" or (kind != "allow" and prog not in RUNNABLE):
        die(f"refused: {why or 'this command is not one THANOS may start unattended'}. Run it directly so the normal permissions decide")
    name = _opt(flags, "--name", "") or f"{re.sub(r'[^A-Za-z0-9_-]', '-', prog)[:20]}-{len(st.get('procs') or []) + 1}"
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", name) or any(p["name"] == name for p in st.get("procs") or []):
        die(f"invalid or repeated process name '{name}'")
    logs = tdir() / "run"
    logs.mkdir(parents=True, exist_ok=True)
    log = logs / f"{st['batch']}-{name}.log"
    with log.open("ab") as out:
        proc = subprocess.Popen(["bash", "-c", text], cwd=cwd, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
    st.setdefault("procs", []).append({"name": name, "pid": proc.pid, "pgid": proc.pid, "cmd": text, "cwd": cwd, "log": str(log), "started": int(time.time())})
    _save(bp, st)
    ws.log("thanos.run", "ok", "", st["batch"], f"{name} pid {proc.pid}: {text[:80]}")
    print(f"started {name} (pid {proc.pid}) in {cwd}\n  log: {log}\n  stop it with: ms-workspace thanos kill {name}  (it also stops on pause, done and stop)")
    return 0


def _procs(ws: Workspace | None, args: list[str]) -> int:
    st = _load(_pick(ws, args))
    rows = st.get("procs") or []
    for p in rows:
        print(f"{p['name']:<20} pid {p['pid']:<8} {'running' if _group_alive(p['pgid']) else 'exited':<8} {p['cmd'][:60]}  [{p['log']}]")
    if not rows:
        print("(no background processes started with thanos run)")
    return 0


def _kill_cmd(ws: Workspace | None, args: list[str]) -> int:
    bp = _pick(ws, args)
    st = _load(bp)
    wanted = _positional(args)
    rows = st.get("procs") or []
    if "--all" not in args and not wanted:
        die("usage: thanos kill NAME|PID|--all")
    hit = [p for p in rows if "--all" in args or p["name"] in wanted or str(p["pid"]) in wanted]
    if not hit:
        die("no such process started with thanos run (see: thanos procs)")
    for p in hit:
        ok = _stop_proc(p)
        print(f"{p['name']} (pid {p['pid']}): " + ("stopped" if ok else "still running"))
        if ok:
            rows.remove(p)
    st["procs"] = rows
    _save(bp, st)
    if ws is not None:
        ws.log("thanos.kill", "ok", "", st["batch"], ",".join(p["name"] for p in hit))
    return 0


# --------------------------------------------------------- unblock, allow rules
def _unpark(batch_path: Path, name: str) -> bool:
    path = ledger_path(batch_path)
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return False
    for t in tasks(batch_path):
        if t["mark"] == "!" and re.match(rf"^{re.escape(name)}(?![\w-])", t["text"]):
            lines[t["line"]] = lines[t["line"]].replace("[!]", "[ ]", 1)
            path.write_text("\n".join(lines) + "\n")
            return True
    return False


def _unblock(ws: Workspace | None, args: list[str]) -> int:
    names = _positional(args)
    if not names:
        die("usage: thanos unblock <task>")
    bp = _pick(ws, args)
    st = _load(bp)
    if not _unpark(bp, names[0]):
        die(f"no parked [!] task named {names[0]} in THANOS.md")
    _append_section(bp, "Blockers", f"- {time.strftime('%H:%M')} unblocked: {names[0]}")
    if ws is not None:
        ws.log("thanos.unblock", "ok", "", st["batch"], names[0])
    print(f"task {names[0]} is open again" + (f"; the mission is {st['status']}: 'thanos resume {st['batch']}' continues it" if st["status"] != "working" else ""))
    return 0


def note_asked(m: dict, command: str) -> None:
    """Called by the guard for a command it left to the normal permissions: `allow-suggest` reads these."""
    path = Path(m["batch_path"]) / ASKED
    try:
        if path.is_file() and path.stat().st_size > 200_000:
            return
        with path.open("a") as f:
            f.write(json.dumps({"c": command[:400], "t": int(time.time())}) + "\n")
    except OSError:
        pass


def note_blocked(m: dict, command: str, why: str) -> None:
    try:
        (Path(m["batch_path"]) / LAST_BLOCK).write_text(json.dumps({"c": command[:200], "why": why[:200], "t": int(time.time())}))
    except OSError:
        pass


SUB_PROGS = {"git", "ms-workspace", "pnpm", "npm", "yarn", "bun", "docker", "podman", "npx", "cargo", "go", "dotnet", "make"}
BROAD_PROGS = {"python", "python3", "node", "bash", "sh", "perl", "ruby", "java", "deno", "bun", "npx"}


def _rule(seg: list[str]) -> tuple[str, bool] | None:
    from .guard import _strip
    seg = _strip(seg)
    if not seg:
        return None
    prog, words = os.path.basename(seg[0]), [a for a in seg[1:] if not a.startswith("-")]
    if prog in ("cd", "export", "set", "source", "."):
        return None
    rule = f"Bash({prog} {words[0]}:*)" if prog in SUB_PROGS and words else f"Bash({prog}:*)"
    return rule, prog in BROAD_PROGS


def _allow_suggest(ws: Workspace | None, args: list[str]) -> int:
    from .guard import _segments
    from .thanos_guard import verdict
    bp = _pick(ws, args)
    st = _load(bp)
    m = {**st, "batch_path": str(bp), "root": str(ws.root) if ws else ""}
    counts: dict[str, list] = {}
    try:
        rows = [json.loads(x) for x in (bp / ASKED).read_text().splitlines() if x.strip()]
    except (OSError, ValueError):
        rows = []
    for row in rows:
        try:
            segs = _segments(row["c"])
        except (ValueError, KeyError):
            continue
        for seg in segs:
            kind, _ = verdict(" ".join(seg), m, cwd=str(bp))
            r = _rule(seg) if kind == "" else None
            if r:
                counts.setdefault(r[0], [0, r[1]])[0] += 1
    narrow = sorted((k for k, v in counts.items() if not v[1]), key=lambda k: -counts[k][0])
    broad = sorted((k for k, v in counts.items() if v[1]), key=lambda k: -counts[k][0])
    if "--json" in args:
        print(json.dumps({"allow": narrow, "broad": broad, "asked": len(rows)}))
        return 0
    if not counts:
        print("nothing to suggest: every command of this mission was approved or blocked by the strict guard")
        return 0
    print(f"{len(rows)} command(s) went to the normal permission prompt. Rules that would have approved them:")
    for k in narrow:
        print(f"  {counts[k][0]:>3}  {k}")
    for k in broad:
        print(f"  {counts[k][0]:>3}  {k}   (broad: it lets Claude run any code; review before adding)")
    print("Add the ones you accept to permissions.allow in .claude/settings.local.json (this tool never edits settings).")
    return 0


# ------------------------------------------------------------ report and extend
def _report(ws: Workspace, bp: Path, st: dict) -> str:
    from .core import base_ref
    ts, sec = tasks(bp), ledger_sections(bp)
    secs = int(time.time() - st.get("started", time.time()))
    out = [f"# THANOS report: {st['batch']} (generation {st.get('generation', 1)})", "", f"Goal: {st['goal']}", "",
           f"- steps {st['steps']}/{st['max_steps']}, Opus reviews {st['opus_used']}/{st['max_opus']}, blockers {st['blockers']}, elapsed {secs // 3600}h{secs % 3600 // 60:02d}m",
           "", "## Success criteria", "(verify each with a command and its result; this list is what the mission promised)"]
    out += [f"- 🟡 {c} (evidence: not recorded yet)" for c in sec["criteria"]] or ["- (none written)"]
    out += ["", "## Tasks"]
    for label, mark, icon in (("done", "x", "🟢"), ("parked", "!", "🔴"), ("open", " ", "🟡")):
        items = [t["text"] for t in ts if t["mark"] == mark]
        out += [f"- {icon} {label}: {len(items)}"] + [f"  - {x[:100]}" for x in items]
    out += ["", "## Changes against the base branch"]
    for r, wt in _repo_dirs(ws, st):
        ref = base_ref(wt, ws.base(r))
        n = git(wt, "rev-list", "--count", f"{ref}..HEAD").stdout.strip() or "?"
        stat = git(wt, "diff", "--shortstat", f"{ref}...HEAD").stdout.strip() or "no changes"
        out.append(f"- {r}: {n} commit(s), {stat}")
    for title, key in (("Decisions", "decisions"), ("Failed attempts", "failed"), ("Blockers", "blockers")):
        out += ["", f"## {title}"] + ([f"- {x}" for x in sec[key]] or ["- none"])
    out += ["", "🟡 Not verified: (the mission's final answer states what was skipped and the risk left)", "", "Next for you: ms-workspace plan, then /dynamia:ship. THANOS never ships."]
    text = "\n".join(out) + "\n"
    (bp / REPORT).write_text(text)
    return text


def _validate_extend(ws: Workspace, bp: Path, st: dict, skip_tests: bool) -> tuple[list[str], list[str]]:
    """(problems, notes): a finished mission may be extended only when its batch is intact, merged, clean and green."""
    problems, notes = [], []
    if st["status"] != "done":
        problems.append(f"the mission is '{st['status']}', not done: {'resume it' if st['status'] == 'paused' else 'let it finish'} (thanos resume / thanos done)")
    open_t = [t["text"] for t in tasks(bp) if t["mark"] == " "]
    if open_t:
        problems.append(f"{len(open_t)} task(s) still open (first: {open_t[0][:60]})")
    parked = [t["text"] for t in tasks(bp) if t["mark"] == "!"]
    if parked:
        notes.append(f"{len(parked)} parked task(s) carry over as context, not as work: {', '.join(x.split(':')[0] for x in parked)[:100]}")
    prefix = f"agent/{st['batch']}/"
    for r, wt in _repo_dirs(ws, st):
        if not wt.is_dir():
            problems.append(f"{r}: the worktree is gone")
            continue
        cur = git(wt, "branch", "--show-current").stdout.strip()
        if cur != st["branch"]:
            problems.append(f"{r}: on '{cur}', expected the batch branch {st['branch']}")
        if git(wt, "status", "--porcelain").stdout.strip():
            problems.append(f"{r}: uncommitted changes")
        for line in git(wt, "branch", "--list", f"{prefix}*", "--format=%(refname:short)").stdout.split():
            if git(wt, "rev-list", "--count", f"{st['branch']}..{line}").stdout.strip() not in ("", "0"):
                problems.append(f"{r}: task branch {line} has commits that were never merged into {st['branch']}")
    if skip_tests:
        notes.append("tests were skipped (--skip-tests): the finished work was NOT validated")
    elif not problems:
        from . import runner
        try:
            rc = runner.cmd_test(ws, ["t1", st["batch"]])
        except SystemExit as e:
            rc = e.code if isinstance(e.code, int) else 1
        if rc != 0:
            problems.append("test t1 of the batch does not pass: fix it before extending")
    return problems, notes


def _extend(ws: Workspace, args: list[str]) -> int:
    bp = _find_batch(ws, args)
    st = _load(bp)
    goal = _opt(args, "--goal", "")
    if not goal and "--check" not in args:
        die('usage: thanos extend <batch> --goal "<what to add>" [--check] [--skip-tests] [--max-steps N | --until-usage PCT]')
    problems, notes = _validate_extend(ws, bp, st, "--skip-tests" in args)
    for n in notes:
        print(f"note: {n}")
    if problems:
        print("cannot extend this mission yet:")
        print("\n".join(f"  - {x}" for x in problems))
        return 1
    if "--check" in args:
        print(f"ok: '{st['batch']}' (generation {st.get('generation', 1)}) is done, merged, clean and passes t1; it can be extended")
        return 0
    gen, sec = st.get("generation", 1), ledger_sections(bp)
    done = [t["text"] for t in tasks(bp) if t["mark"] == "x"]
    parked = [t["text"] for t in tasks(bp) if t["mark"] == "!"]
    for src, dst in ((LEDGER, f"THANOS.g{gen}.md"), (REPORT, f"THANOS-REPORT.g{gen}.md")):
        if (bp / src).is_file():
            os.replace(bp / src, bp / dst)
    prev = [f"\n## Previous mission (generation {gen}, finished)", f"Goal: {st['goal']}", f"Full history: THANOS.g{gen}.md in this folder (read it before planning).",
            "Done (not to be redone):"] + [f"- done: {x[:100]}" for x in done]
    if parked:
        prev += ["Parked (blocked then; not part of this mission unless the new goal says so):"] + [f"- parked: {x[:100]}" for x in parked]
    ledger_path(bp).write_text(TEMPLATE.format(batch=st["batch"], goal=goal) + "\n".join(prev) + "\n")
    for key, title in (("decisions", "Decisions"), ("failed", "Failed attempts")):
        for line in sec[key]:
            _append_section(bp, title, f"- (gen {gen}) {line}")
    rest = [a for a in args if a not in ("--check", "--skip-tests")]
    pos = _positional(rest)
    if pos:
        rest.remove(pos[0])
    rc = _start(ws, [st["batch"], *rest], extra={"generation": gen + 1, "extends": st["goal"]})
    if rc == 0:
        print(f"  extends generation {gen}: its decisions and failed attempts were carried into THANOS.md; plan the new tasks there")
    return rc


# ------------------------------------------------------------------------ panel
PANEL_SECTIONS = {"criteria": "Success criteria", "decisions": "Decisions", "failed": "Failed attempts", "blockers": "Blockers"}


def ledger_sections(batch_path: Path) -> dict[str, list[str]]:
    """The bullet lines under Decisions, Failed attempts and Blockers (template comments dropped)."""
    out: dict[str, list[str]] = {k: [] for k in PANEL_SECTIONS}
    try:
        lines = ledger_path(batch_path).read_text().splitlines()
    except OSError:
        return out
    key, comment = "", False
    for line in lines:
        if line.startswith("## "):
            key, comment = next((k for k, v in PANEL_SECTIONS.items() if line[3:].strip() == v), ""), False
            continue
        text = line.strip()
        if comment or text.startswith("<!--"):
            comment = "-->" not in text
            continue
        item = text[2:].strip() if text.startswith(("- ", "* ")) else text
        if key and item and not item.startswith("(each one"):
            out[key].append(item)
    return out


def _panel_pointer(args: list[str]) -> dict | None:
    """This session's mission; without --session, the one touched last (working ones first)."""
    sid = _opt(args, "--session", "")
    if sid:
        return _read(pointer_path(sid)) if _safe(sid) else None
    ptrs = [p for f in tdir().glob("*.json") if (p := _read(f)) and p.get("batch_path")]
    ptrs.sort(key=lambda p: (p.get("status") == "working", p.get("touched", 0)), reverse=True)
    return ptrs[0] if ptrs else None


def _active_task(ptr: dict, st: dict) -> str:
    """Name of the task whose branch the batch worktree is on, '' between tasks."""
    try:
        ws = Workspace(Path(ptr["root"]))
        prefix = f"agent/{st['batch']}/"
        for r in batch_repos(ws, st["batch"]):
            cur = git_out(Path(ptr["batch_path"]) / r, "branch", "--show-current")
            if cur.startswith(prefix):
                return cur[len(prefix):]
    except Exception:
        pass
    return ""


def panel_data(ptr: dict | None) -> dict:
    st = _read(Path(ptr["batch_path"]) / STATE) if ptr else None
    if not ptr or not st:
        return {"mission": None}
    bp = Path(ptr["batch_path"])
    active = _active_task(ptr, st)
    items = []
    for t in tasks(bp):
        name = re.split(r"[:\s]", t["text"], 1)[0]
        items.append({"mark": t["mark"], "size": t["size"], "text": t["text"], "active": bool(active) and t["mark"] == " " and name == active})
    mission = {k: st.get(k, "") for k in ("batch", "branch", "goal", "status", "steps", "max_steps", "until_usage", "opus_used", "max_opus", "blockers", "started")}
    mission["generation"] = st.get("generation", 1)
    try:
        used = usage_used(Workspace(Path(ptr["root"])))
    except Exception:
        used = None
    procs = [{"name": p["name"], "pid": p["pid"], "alive": _group_alive(p["pgid"]), "cmd": p["cmd"][:80]} for p in st.get("procs") or []]
    return {"mission": mission, "active": active, "tasks": items, "usage": used, "procs": procs, "last_block": _read(bp / LAST_BLOCK),
            **ledger_sections(bp)}


def cmd_panel(args: list[str]) -> int:
    """JSON for the side panel. Fails open: anything unreadable is 'no mission'."""
    try:
        data = panel_data(_panel_pointer(args))
    except Exception:
        data = {"mission": None}
    print(json.dumps(data))
    return 0


# ------------------------------------------------------------------------ hooks
def _emit(obj: dict) -> None:
    print(json.dumps(obj))


def hook_stop() -> int:
    """Stop hook: while the mission has work left, ask Claude to keep going. Fails open: any error lets it stop."""
    try:
        payload = json.loads(sys.stdin.read())
        m = session_mission(payload.get("session_id", ""))
        if not m:
            return 0
        return _stop_step(m)
    except Exception:
        return 0


def usage_used(ws: Workspace) -> float | None:
    """Highest used percentage of the 5h and 7d plan windows in the usage snapshot; None when there is no usable data."""
    from .usage import evaluate, snapshot_path
    try:
        ev = evaluate(json.loads(snapshot_path().read_text()), time.time(), 70, 90, 0)
    except (OSError, ValueError, KeyError):
        return None
    known = [w["used"] for w in (ev["session"], ev["week"]) if w.get("state") == "active"]
    return max(known) if known else None


def _stop_step(m: dict) -> int:
    from .handoff import usage_level
    ws, bp = Workspace(Path(m["root"])), Path(m["batch_path"])
    st = _load(bp)
    until = st.get("until_usage") or 0
    waiting = st.get("waiting_until", 0) > time.time()
    if waiting:
        # `thanos wait` buys exactly one uncounted stop (the one that waits for the background agent). Plan usage is
        # still enforced, and the next stop after the notification wakes Claude is a normal, counted step.
        used = usage_used(ws)
        if usage_level(ws) >= 2 or (until and used is not None and used >= until):
            st["waiting_until"] = 0
            _save(bp, st)
        else:
            st["waiting_until"] = 0
            _save(bp, st)
            return 0
    st["steps"] += 1
    sig = _signature(ws, st["batch"], bp)
    st["stalls"] = st["stalls"] + 1 if sig == st.get("signature") else 0
    st["signature"] = sig
    ts = tasks(bp)
    todo = [t for t in ts if t["mark"] == " "]
    pause = ""
    if usage_level(ws) >= 2:
        pause = "plan usage is critical"
    elif until and (used := usage_used(ws)) is None:
        pause = f"there is no plan usage data to enforce --until-usage {num_str(until)} (is the status line running?)"
    elif until and used >= until:
        pause = f"plan usage reached {used:.0f}% (the ceiling is {num_str(until)}%)"
    elif st["steps"] > st["max_steps"]:
        pause = f"the step cap ({st['max_steps']}) was reached"
    elif st["stalls"] >= 3:
        pause = "three steps in a row made no progress"
    if pause:
        _finish(ws, bp, st, "paused", pause)
        _emit({"systemMessage": f"THANOS paused: {pause}. State saved (handoff + {LEDGER}); resume with: ms-workspace thanos resume {st['batch']}"})
        return 0
    _save(bp, st)
    _sync_pointers(str(bp), "working")
    where = f"step {st['steps']}/{st['max_steps']}"
    if todo:
        nxt = todo[0]["text"][:100]
        reason = (f"THANOS {where}. {len(todo)} task(s) open; next: {nxt}. Keep going without asking; pick the next task with "
                  "'ms-workspace thanos task start <name>'. Do not repeat an approach listed under Failed attempts.")
    else:
        reason = (f"THANOS {where}. No open tasks. Run the final validation: ms-workspace test t1, check every success criterion with "
                  "evidence, then the final Opus review if one is left, fix what it finds, and finish with 'ms-workspace thanos done'.")
    _emit({"decision": "block", "reason": reason})
    return 0


def hook_context() -> int:
    """SessionStart hook: after a compaction or a resume, re-inject the short state of the mission."""
    try:
        payload = json.loads(sys.stdin.read())
        m = session_mission(payload.get("session_id", ""), any_status=True)
        if not m:
            return 0
        bp = Path(m["batch_path"])
        ts = tasks(bp)
        lines = [f"THANOS mission '{m['batch']}' is {m['status']}. {_summary(_load(bp), bp)}", f"Goal: {m['goal']}", f"Ledger: {ledger_path(bp)} (read it; it holds the decisions and failed attempts)"]
        lines += [f"  open: {t['text'][:90]}" for t in ts if t["mark"] == " "][:5]
        if m["status"] != "done":
            lines += _where(Workspace(Path(m["root"])), _load(bp))
        if m["status"] == "working":
            lines.append("Continue the mission: no questions, work inside the batch worktree, never ship or push anything but the batch branch.")
        print("\n".join(lines))
    except Exception:
        pass
    return 0


def hook_guard() -> int:
    """PreToolUse for Edit, Write and Agent during a mission: edits stay inside the batch, only Opus reviews may be delegated."""
    try:
        payload = json.loads(sys.stdin.read())
        m = session_mission(payload.get("session_id", ""))
        if not m:
            return 0
        tool, inp = payload.get("tool_name", ""), payload.get("tool_input") or {}
        if tool == "Agent":
            return _agent_gate(m, inp)
        path = inp.get("file_path") or inp.get("notebook_path") or ""
        if not path:
            return 0
        from .thanos_guard import inside
        cwd = payload.get("cwd") or os.getcwd()
        base = os.path.basename(path)
        if not inside(path, m, cwd) or base == STATE or "/.git/" in os.path.realpath(os.path.join(cwd, path)) + "/":
            print(f"THANOS blocked: {tool} outside the batch worktree or on its own state ({path}). Edit only files inside {m['batch_path']}. "
                  f"Record it with: ms-workspace thanos block \"{tool} {base}\" and continue with another task.", file=sys.stderr)
            return 2
        _emit({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow", "permissionDecisionReason": "THANOS: edit inside the batch"}})
    except Exception:
        pass
    return 0


def _agent_gate(m: dict, inp: dict) -> int:
    kind = inp.get("subagent_type") or ""
    if kind not in OPUS_AGENTS or inp.get("run_in_background"):
        print("THANOS blocked: only the Opus reviewer (dynamia:boss), in the foreground, may be launched during a mission: other agents eat the context. "
              "Search with Grep/Glob yourself.", file=sys.stderr)
        return 2
    st = _read(Path(m["batch_path"]) / STATE) or m
    if st["opus_used"] >= st["max_opus"]:
        print(f"THANOS blocked: the {st['max_opus']} Opus review(s) of this mission are used (start, end and one rescue). Decide on your own and note it under Decisions.", file=sys.stderr)
        return 2
    st["opus_used"] += 1
    _write(Path(m["batch_path"]) / STATE, {k: v for k, v in st.items() if k not in ("batch_path", "root", "sid")})
    left = st["max_opus"] - st["opus_used"]
    _emit({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow",
                                   "permissionDecisionReason": f"THANOS Opus review {st['opus_used']}/{st['max_opus']} ({left} left). Ask for a report of at most 25 lines."}})
    return 0
