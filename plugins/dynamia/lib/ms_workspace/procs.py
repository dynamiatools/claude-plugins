"""Processes: what is heavy, who holds a port, what an agent left running, and a guarded kill."""
from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import time
from pathlib import Path

from .core import Workspace, die, int_arg

PROTECTED = re.compile(r"(^|/)(systemd|init|launchd|sshd|tmux|screen|login|dbus-daemon|claude)(\s|$|:)")
DEV_TOOLS = re.compile(r"(^|/)(java|node|npm|npx|pnpm|yarn|mvn|gradle|python3?|uvicorn|gunicorn|flask|vite|next|nuxt|esbuild|webpack|cloudflared|docker-proxy)(\s|$)")


class Proc:
    def __init__(self, pid, ppid, user, cpu, mem, rss, age, stat, cmd):
        self.pid, self.ppid, self.user, self.cpu, self.mem, self.rss, self.age, self.stat, self.cmd = pid, ppid, user, cpu, mem, rss, age, stat, cmd

    def line(self, with_cwd: str = "") -> str:
        return (f"{self.pid:>7} {self.user[:9]:<9} cpu {self.cpu:>5.1f}% mem {self.mem:>4.1f}% {self.rss / 1024:>7.0f}M  {fmt_age(self.age):>7}  "
                f"{self.cmd[:90]}" + (f"  [{with_cwd}]" if with_cwd else ""))


def kill_hint(cmd: str) -> str:
    """How to end a protected process `ps kill` refuses: a tmux session is ended by name, not by pid."""
    m = re.search(r"(^|/)tmux\b.*?(?:new-session|new|attach|attach-session)\b.*?\s-s\s+(\S+)", cmd)
    if m:
        return f"end the tmux session with: tmux kill-session -t {m.group(2)}"
    return ""


def parse_etime(text: str) -> int:
    days, _, rest = text.partition("-") if "-" in text else ("0", "", text)
    parts = [int(x) for x in rest.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    return int(days) * 86400 + parts[0] * 3600 + parts[1] * 60 + parts[2]


def fmt_age(s: int) -> str:
    return f"{s // 86400}d{s % 86400 // 3600}h" if s >= 86400 else f"{s // 3600}h{s % 3600 // 60}m" if s >= 3600 else f"{s // 60}m{s % 60}s"


def snapshot() -> list[Proc]:
    if not shutil.which("ps"):
        die("ps is not available on this system")
    r = subprocess.run(["ps", "-axo", "pid=,ppid=,user=,pcpu=,pmem=,rss=,etime=,stat=,args="], capture_output=True, text=True)
    out = []
    for line in r.stdout.splitlines():
        parts = line.split(None, 8)
        if len(parts) < 9:
            continue
        try:
            out.append(Proc(int(parts[0]), int(parts[1]), parts[2], float(parts[3]), float(parts[4]), int(parts[5]), parse_etime(parts[6]), parts[7], parts[8]))
        except ValueError:
            pass
    return out


def cwd_of(pid: int) -> str:
    try:
        return os.readlink(f"/proc/{pid}/cwd")
    except OSError:
        return ""


def ancestors(procs: list[Proc]) -> set[int]:
    by = {p.pid: p for p in procs}
    chain, pid = set(), os.getpid()
    while pid in by and pid not in chain and pid > 1:
        chain.add(pid)
        pid = by[pid].ppid
    return chain


def procs_in_dir(directory: Path) -> list[tuple[int, str]]:
    """Processes of the current user whose working directory is inside `directory` (Linux; empty elsewhere)."""
    if not Path("/proc/self").exists():
        return []
    root, me, found = str(directory.resolve()), os.getuid(), []
    mine = ancestors(snapshot())
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) in mine or int(entry.name) == os.getpid():
            continue
        try:
            if entry.stat().st_uid != me:
                continue
            cwd = os.readlink(entry / "cwd")
            if cwd == root or cwd.startswith(root + "/"):
                found.append((int(entry.name), (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace").strip()[:80]))
        except OSError:
            continue
    return found


def label_for(ws: Workspace | None, cwd: str) -> str:
    if not cwd or ws is None:
        return cwd
    rel = ws.rel_parts(cwd)
    if rel is None:
        return cwd
    if ws is not None and rel[:1] == (ws.batch_dir.name,) and len(rel) >= 3:
        return f"batch {rel[1]}/{rel[2] if rel[2] != '.agents' else rel[-1]}"
    return rel[0] if rel else "workspace root"


def cmd_top(args: list[str]) -> int:
    top, by, user, text = 10, "cpu", "", ""
    if "--mine" in args:
        args = [a for a in args if a != "--mine"]
        user = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
    it = iter(args)
    for a in it:
        if a == "--top":
            try:
                top = int(next(it))
            except (StopIteration, ValueError):
                die("--top needs a number")
        elif a == "--by":
            by = next(it, "cpu")
            if by not in ("cpu", "mem"):
                die("--by is cpu or mem")
        elif a == "--user":
            user = next(it, "")
        elif a == "--filter":
            text = next(it, "").lower()
        else:
            die(f"ps: unknown option {a}")
    procs = [p for p in snapshot() if (not user or p.user == user) and (not text or text in p.cmd.lower()) and p.pid != os.getpid()]
    procs.sort(key=lambda p: -(p.cpu if by == "cpu" else p.rss))
    print(f"{len(procs)} processes; top {min(top, len(procs))} by {by} (cpu is ps's average since the process started)")
    for p in procs[:top]:
        print(p.line())
    return 0


def cmd_tree(args: list[str]) -> int:
    if not args:
        die("usage: ps tree <pid|text>")
    procs = snapshot()
    kids: dict[int, list[Proc]] = {}
    for p in procs:
        kids.setdefault(p.ppid, []).append(p)
    roots = [p for p in procs if (str(p.pid) == args[0] or (not args[0].isdigit() and args[0].lower() in p.cmd.lower())) and p.pid != os.getpid()]
    if not roots:
        print("(nothing matches)")
        return 0

    def show(p: Proc, depth: int, seen: set):
        if p.pid in seen or depth > 8:
            return
        seen.add(p.pid)
        print("  " * depth + f"{p.pid} {p.cmd[:80]}  ({p.rss / 1024:.0f}M, {fmt_age(p.age)})")
        for c in kids.get(p.pid, []):
            show(c, depth + 1, seen)

    seen: set = set()
    for r in roots[:5]:
        if r.ppid not in {x.pid for x in roots}:
            show(r, 0, seen)
    return 0


def cmd_find(args: list[str]) -> int:
    if not args:
        die("usage: ps find <text>")
    hits = [p for p in snapshot() if args[0].lower() in p.cmd.lower() and p.pid != os.getpid() and "ms-workspace ps find" not in p.cmd]
    print(f"{len(hits)} match(es)")
    for p in hits[:30]:
        print(p.line())
    return 0


def listeners() -> list[dict]:
    """Listening TCP sockets with their owning process (ss on Linux, lsof elsewhere)."""
    rows = []
    if shutil.which("ss"):
        out = subprocess.run(["ss", "-ltnpH"], capture_output=True, text=True).stdout
        for line in out.splitlines():
            parts = line.split()
            if len(parts) < 5:
                continue
            m = re.search(r'users:\(\("([^"]+)",pid=(\d+)', line)
            addr, _, port = parts[3].rpartition(":")
            rows.append({"port": int(port) if port.isdigit() else 0, "addr": addr, "pid": int(m.group(2)) if m else None, "proc": m.group(1) if m else "(not visible: another user)"})
    elif shutil.which("lsof"):
        out = subprocess.run(["lsof", "-iTCP", "-sTCP:LISTEN", "-nP", "-Fpcn"], capture_output=True, text=True).stdout
        pid, name = None, ""
        for line in out.splitlines():
            if line.startswith("p"):
                pid = int(line[1:])
            elif line.startswith("c"):
                name = line[1:]
            elif line.startswith("n"):
                addr, _, port = line[1:].rpartition(":")
                rows.append({"port": int(port) if port.isdigit() else 0, "addr": addr, "pid": pid, "proc": name})
    else:
        die("neither ss nor lsof is available to list listening ports")
    return rows


def cmd_ports(ws, args: list[str]) -> int:
    only = None
    if "--port" in args:
        try:
            only = int(args[args.index("--port") + 1])
        except (IndexError, ValueError):
            die("--port needs a number")
    rows = sorted((r for r in listeners() if only is None or r["port"] == only), key=lambda r: (r["port"], r["pid"] or 0))
    hidden = [r for r in rows if r["pid"] is None]
    if "--all" not in args and only is None:
        rows = [r for r in rows if r["pid"] is not None]   # sockets of other users are listed only on request
    if not rows:
        print(f"nothing is listening on port {only}" if only else "(no listening TCP ports you can see)")
        if only and hidden:
            print(f"a socket on {only} exists but belongs to another user (the process is not visible)")
        return 0
    seen = set()
    for r in rows:
        key = (r["port"], r["pid"])
        if key in seen:
            continue
        seen.add(key)
        cwd = cwd_of(r["pid"]) if r["pid"] else ""
        print(f"{r['port']:>6}  {r['addr']:<15} pid {r['pid'] or '-':<8} {r['proc']}" + (f"  [{label_for(ws, cwd)}]" if cwd and ws else ""))
    if hidden and "--all" not in args and only is None:
        print(f"({len(hidden)} more listener(s) belong to other users; --all shows them)")
    return 0


def cmd_leftovers(ws, args: list[str]) -> int:
    hours, limit = 4.0, 20
    if "--hours" in args:
        try:
            hours = float(args[args.index("--hours") + 1])
        except (IndexError, ValueError):
            die("--hours needs a number")
    if "--limit" in args:
        limit = int_arg(iter(args[args.index("--limit") + 1:]), "--limit", limit)
    procs = snapshot()
    skip, me = ancestors(procs), os.environ.get("USER") or os.environ.get("LOGNAME")
    found = []
    for p in procs:
        if p.pid in skip or p.pid == os.getpid() or (me and p.user != me) or PROTECTED.search(p.cmd) or not DEV_TOOLS.search(p.cmd):
            continue
        if p.age >= hours * 3600 or p.ppid == 1:
            found.append(p)
    print(f"{len(found)} dev process(es) of yours that are older than {hours:g}h or orphaned (parent pid 1)")
    for p in sorted(found, key=lambda p: -p.rss)[:limit]:
        print(p.line(label_for(ws, cwd_of(p.pid))))
    if found:
        print("Stop one with: ms-workspace ps kill <pid> --yes   (it checks the process first)")
    return 0


def cmd_kill(ws, args: list[str]) -> int:
    yes, sig, pids, it = "--yes" in args, signal.SIGTERM, [], iter(a for a in args if a != "--yes")
    for a in it:
        if a == "--signal":
            name = next(it, "TERM").upper().removeprefix("SIG")
            if name not in ("TERM", "KILL", "INT", "HUP"):
                die("--signal is TERM, KILL, INT or HUP")
            sig = getattr(signal, "SIG" + name)
        elif a.isdigit():
            pids.append(int(a))
        else:
            die(f"ps kill: unexpected argument '{a}'")
    if not pids:
        die("usage: ps kill <pid...> [--signal TERM|KILL|INT|HUP] [--yes]")
    signame = sig.name.removeprefix("SIG")
    procs = {p.pid: p for p in snapshot()}
    mine, me = ancestors(list(procs.values())), os.environ.get("USER") or os.environ.get("LOGNAME")
    bad = False
    for pid in pids:
        p = procs.get(pid)
        if p is None:
            print(f"  {pid}: no such process")
            bad = True
        elif pid <= 1 or pid in mine or pid == os.getpid():
            print(f"  {pid}: refused, it is this session or one of its parents")
            bad = True
        elif me and p.user != me:
            print(f"  {pid}: refused, it belongs to {p.user}")
            bad = True
        elif PROTECTED.search(p.cmd):
            hint = kill_hint(p.cmd)
            print(f"  {pid}: refused, protected process ({p.cmd[:50]})" + (f"; {hint}" if hint else ""))
            bad = True
        elif not yes:
            print(f"  {pid}: would send {signame} to: {p.cmd[:90]}  (age {fmt_age(p.age)}, {p.rss / 1024:.0f}M)")
        else:
            os.kill(pid, sig)
            for _ in range(50):
                time.sleep(0.1)
                if not Path(f"/proc/{pid}").exists() and not any(q.pid == pid and "Z" not in q.stat for q in snapshot()):
                    break
            alive = any(q.pid == pid and "Z" not in q.stat for q in snapshot())
            print(f"  {pid}: {signame} sent; " + ("still running (try --signal KILL)" if alive else "gone"))
            bad = bad or alive
            if ws is not None:
                ws.log("ps.kill", "fail" if alive else "ok", "", "", f"{pid} {signame}: {p.cmd[:60]}")
    if not yes and not bad:
        print("(plan only; pass --yes to send the signal)")
    return 1 if bad else 0


def cmd_ps(ws: Workspace | None, args: list[str]) -> int:
    sub = args[0] if args and not args[0].startswith("-") else ""
    rest = args[1:] if sub else args
    if sub == "tree":
        return cmd_tree(rest)
    if sub == "find":
        return cmd_find(rest)
    if sub == "ports":
        return cmd_ports(ws, rest)
    if sub == "leftovers":
        return cmd_leftovers(ws, rest)
    if sub == "kill":
        return cmd_kill(ws, rest)
    if sub:
        die("usage: ps [--top N] [--by cpu|mem] [--user U] [--filter text] | tree <pid|text> | find <text> | ports [--port N] | leftovers [--hours N] | kill <pid> [--yes]")
    return cmd_top(rest)
