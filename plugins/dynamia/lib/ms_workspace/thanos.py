"""THANOS: an autonomous mission inside its own batch worktree.

    ms-workspace thanos start <batch> [--goal T] [--max-steps N | --until-usage PCT] [--max-opus N] [--opus-used N] [--push-every N] [--deny-host H]
    ms-workspace thanos resume <batch>            re-attach this session to a mission that is still working
    ms-workspace thanos estimate <batch>          steps the task list in THANOS.md needs, and the cap that would be used
    ms-workspace thanos status [batch]            one line: status, steps, tasks, Opus reviews
    ms-workspace thanos task start|done <name>    a branch per task, merged into the batch branch when it is done
    ms-workspace thanos block [--task NAME] "<what and why>"   record something the guard refused (and park that task [!]), then move on
    ms-workspace thanos wait [MINUTES]            waiting for a background agent: stops in that window are not counted as steps
    ms-workspace thanos pause "<why>" | done [--force] | stop
    ms-workspace thanos stop-hook | context       hooks (Stop, SessionStart)
    ms-workspace thanosguard                      hook (PreToolUse for Edit, Write and Agent)

State: <batch>/THANOS.md (the ledger the model keeps: goal, tasks `- [ ] [S|M|L] name`, decisions, failed attempts, blockers)
and <batch>/.thanos.json (counters and limits, written only by this tool). A pointer per session in the cache folder tells
the hooks which mission a session belongs to and feeds the status line badge.

A "step" is one autonomous turn: each time Claude would stop while tasks remain, the Stop hook counts one and asks it to
continue. The mission pauses on the step cap (or, with --until-usage, when plan usage reaches that percentage), on critical plan
usage, or after three steps without progress. While `thanos wait` is active the Stop hook lets Claude stop without counting a step."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

from .core import Workspace, batch_repos, die, git, git_ok, git_out, need_batch
from .usage import cache_dir

UNTIL_USAGE_STEPS = 10000
DEFAULTS = {"max_steps": 30, "max_opus": 3, "push_every": 3, "stale_hours": 12}
SIZES = {"S": 2, "M": 4, "L": 8}
LEDGER, STATE = "THANOS.md", ".thanos.json"
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
        if t["mark"] == " " and re.match(rf"^{re.escape(name)}\b", t["text"]):
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
    if ws is None:
        die("THANOS needs a workspace (run the dynamia:workspace-init skill first)")
    handler = {"start": _start, "resume": _resume, "estimate": _estimate, "status": _status, "task": _task, "block": _block,
               "wait": _wait, "pause": _pause, "done": _done, "stop": _stop}.get(sub)
    if handler is None:
        die("usage: thanos start|resume|estimate|status|task|block|wait|pause|done|stop (see ms-workspace help)")
    return handler(ws, rest)


VALUE_FLAGS = {"--goal", "--max-steps", "--max-opus", "--opus-used", "--until-usage", "--push-every", "--deny-host", "--task"}


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


def _start(ws: Workspace, args: list[str]) -> int:
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
          "tasks_done": 0, "stalls": 0, "signature": "", "deny_hosts": deny, "stale_hours": cfg(ws, "stale_hours"), "blockers": 0}
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
        if t["mark"] == " " and re.match(rf"^{re.escape(name)}\b", t["text"]):
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
    st["waiting_until"] = time.time() + minutes * 60
    _save(bp, st)
    print(f"waiting for a background agent for up to {num_str(minutes)} minute(s): stops in that window do not count as steps. End your turn; its notification will wake you.")
    return 0


def _finish(ws: Workspace, bp: Path, st: dict, status: str, why: str) -> None:
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
    _finish(ws, bp, st, "done", "mission finished")
    print(_summary(st, bp))
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


def usage_used(ws: Workspace) -> float:
    """Highest used percentage of the 5h and 7d plan windows in the usage snapshot (0 when unknown)."""
    from .usage import evaluate, snapshot_path
    try:
        ev = evaluate(json.loads(snapshot_path().read_text()), time.time(), 70, 90, 0)
    except (OSError, ValueError, KeyError):
        return 0.0
    return max([w["used"] for w in (ev["session"], ev["week"]) if w.get("state") == "active"] or [0.0])


def _stop_step(m: dict) -> int:
    from .handoff import usage_level
    ws, bp = Workspace(Path(m["root"])), Path(m["batch_path"])
    st = _load(bp)
    if st.get("waiting_until", 0) > time.time():
        return 0   # waiting for a background agent: let Claude stop, count nothing, keep the mission working
    st["steps"] += 1
    sig = _signature(ws, st["batch"], bp)
    st["stalls"] = st["stalls"] + 1 if sig == st.get("signature") else 0
    st["signature"] = sig
    ts = tasks(bp)
    todo = [t for t in ts if t["mark"] == " "]
    pause = ""
    until = st.get("until_usage") or 0
    if usage_level(ws) >= 2:
        pause = "plan usage is critical"
    elif until and (used := usage_used(ws)) >= until:
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
