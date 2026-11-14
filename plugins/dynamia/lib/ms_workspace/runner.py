"""Test levels: t0 (what changed here), t1 (changed repos of a batch + critical modules), t2 (end to end)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .core import (Workspace, ahead_of_base, batch_of_cwd, batch_repos, changed_files, die, git, git_out, modules_of,
                   need_batch, toplevel, topo)


def _tail(path: str, n: int = 40) -> str:
    return "\n".join(Path(path).read_text(errors="replace").splitlines()[-n:])


def _run_locked(ws: Workspace, cmd: str, cwd: Path, timeout: float, env: dict | None = None) -> tuple[int, str]:
    """Run `bash -c cmd` under the workspace heavy lock; returns (exit code, output file path)."""
    fd, out = tempfile.mkstemp(prefix="ms-ws-")
    with os.fdopen(fd, "w") as fh, ws.heavy_lock(timeout):
        rc = subprocess.run(["bash", "-c", cmd], cwd=cwd, stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env).returncode
    return rc, out


def _memo_key(ws: Workspace, repo: str, directory: Path, batch: str, cmd: str) -> str:
    """Hash of the code under test (tree, uncommitted changes, untracked files, in-batch dependencies) and the command."""
    h = hashlib.sha1()
    h.update(git_out(directory, "rev-parse", "HEAD^{tree}").encode())
    h.update(git(directory, "diff", "HEAD").stdout.encode())
    for f in git(directory, "ls-files", "-o", "--exclude-standard").stdout.splitlines():
        try:
            h.update(f.encode() + hashlib.sha1((directory / f).read_bytes()).digest())
        except OSError:
            pass
    for d in ws.deps(repo):
        dep = ws.batch_dir / batch / d if batch else None
        if dep and dep.is_dir():
            h.update(git_out(dep, "rev-parse", "HEAD^{tree}").encode())
    h.update(cmd.encode())
    return h.hexdigest()[:20]


def pass_warning(directory: Path, cmd: str) -> str:
    """Why a green run may not have run every test (empty when nothing looks wrong).

    `pnpm -r test` only runs the `test` script of the workspace packages: a root `test` script (typical when
    the tests live in a root `tests/` folder) is skipped, so the run can be green while the suite is never run."""
    if re.search(r"\bpnpm\s+(-r|--recursive)\s+test\b", cmd):
        try:
            root_test = json.loads((directory / "package.json").read_text()).get("scripts", {}).get("test")
        except (OSError, ValueError):
            root_test = None
        if root_test and not re.search(r"(^|\s)(-r|--recursive)(\s|$)", root_test):   # a root script that is itself `pnpm -r test` runs them all
            return (f"the root package.json has its own test script ('{root_test}') that `pnpm -r test` does not run; "
                    "set [repos.<repo>.test] unit = \"pnpm test\" in workspace.toml if the root suite matters")
    return ""


def run_tests(ws: Workspace, repo: str, directory: Path, level: str, batch: str | None = None) -> int:
    batch = batch_of_cwd(ws) if batch is None else batch
    base = ws.base(repo)
    mods = modules_of(directory, changed_files(directory, base))
    if level != "t0":
        mods = sorted(set(mods) | set(ws.repo_cfg(repo).get("critical") or []))
    test_cfg = ws.repo_cfg(repo).get("test") or {}
    cmd = ""
    if mods and test_cfg.get("affected"):
        cmd = test_cfg["affected"].replace("{modules}", shlex.quote(",".join(mods)))
        if "{closure}" in cmd:   # exact dependents from the pom graph, instead of relying on -amd
            from .modules import closure, load_reactor
            graph = load_reactor(directory)
            cmd = cmd.replace("{closure}", shlex.quote(",".join(closure(graph, set(mods)) if graph else mods)))
    cmd = cmd or test_cfg.get("unit") or ""
    if not cmd:
        die(f"no test command configured for '{repo}' in workspace.toml")

    memo_dir = ws.state_dir / "memo"
    memo_dir.mkdir(parents=True, exist_ok=True)
    extra = {**ws.dev_env(repo), **ws.repo_env(repo)}
    key = _memo_key(ws, repo, directory, batch, cmd + (f"\0{sorted(extra.items())}" if extra else ""))
    if not os.environ.get("MS_NO_MEMO") and (memo_dir / f"{repo}-{key}").exists():
        print(f"PASS {level} {repo} (cached: same code and command already passed): {cmd}")
        ws.log(f"test.{level}", "ok", repo, batch, f"cached: {cmd}", key=key, cached=True)
        return 0
    start = started_at = time.time()
    rc, out = _run_locked(ws, cmd, directory, 1800, ws.run_env(repo))
    secs = int(time.time() - start)
    try:
        if rc == 0:
            (memo_dir / f"{repo}-{key}").touch()
            print(f"PASS {level} {repo} ({secs}s): {cmd}")
            warning = pass_warning(directory, cmd)
            if warning:
                print(f"WARN {level} {repo}: {warning}", file=sys.stderr)
            ws.log(f"test.{level}", "ok", repo, batch, cmd, key=key, secs=secs)
        else:
            print(f"FAIL {level} {repo} ({secs}s): {cmd}", file=sys.stderr)
            from .junit import DEFAULT_GLOBS, format_summary, summarize
            summary = summarize(directory, started_at - 5, test_cfg.get("reports") or DEFAULT_GLOBS)
            if summary and (summary["failed"] or summary["errors"]):
                kept = ws.state_dir / "tests" / f"{repo}-{level}.log"
                kept.parent.mkdir(parents=True, exist_ok=True)
                kept.write_text(Path(out).read_text(errors="replace"))
                print("\n".join(format_summary(summary, 8)), file=sys.stderr)
                print(f"full output: {kept}", file=sys.stderr)
            else:
                print(_tail(out), file=sys.stderr)
            ws.log(f"test.{level}", "fail", repo, batch, cmd, key=key, secs=secs)
    finally:
        os.unlink(out)
    return rc


def run_e2e(ws: Workspace, batch: str) -> int:
    cmd = ws.get("e2e", "command")
    if not cmd:
        print("no [e2e] command configured", file=sys.stderr)
        return 2
    erepo = ws.get("e2e", "repo", default="")
    directory = ws.repo_dir(erepo) if erepo else ws.project
    if batch and erepo and (ws.batch_dir / batch / erepo).is_dir():
        directory = ws.batch_dir / batch / erepo
    start = time.time()
    rc, out = _run_locked(ws, cmd, directory, 3600, ws.run_env(erepo) if erepo else None)
    secs = int(time.time() - start)
    try:
        if rc == 0:
            print(f"PASS t2 e2e ({secs}s): {cmd}")
            ws.log("test.t2", "ok", erepo, batch, cmd, secs=secs)
        else:
            print(f"FAIL t2 e2e ({secs}s): {cmd}", file=sys.stderr)
            print(_tail(out), file=sys.stderr)
            ws.log("test.t2", "fail", erepo, batch, cmd, secs=secs)
    finally:
        os.unlink(out)
    return rc


def test_t1(ws: Workspace, batch: str, place: dict | None = None) -> int:
    """t1 for the changed repos of a batch; `place` (repo -> (checkout, branch)) replaces the batch layout for a plain branch."""
    place = place or {r: (ws.batch_dir / batch / r, "") for r in batch_repos(ws, batch)}
    for r in topo(ws, list(place)):
        wt = place[r][0]
        if ahead_of_base(wt, ws.base(r)) == 0:
            print(f"skip {r} (no changes vs base)")
            continue
        rc = run_tests(ws, r, wt, "t1", batch)
        if rc != 0:
            return rc
    return 0


def cmd_test(ws: Workspace, args: list[str]) -> int:
    if "--no-cache" in args:
        os.environ["MS_NO_MEMO"] = "1"
        args = [a for a in args if a != "--no-cache"]
    level = args[0] if args else ""
    arg = args[1] if len(args) > 1 else ""
    if level == "t0":
        top = toplevel()
        name = next((r for r in ws.repo_names() if ws.repo_dir(r).resolve() == top.resolve()), top.name)  # a repo may live at `path`
        return run_tests(ws, name, top, "t0")
    if level == "t1":
        return test_t1(ws, need_batch(ws, arg or batch_of_cwd(ws)))
    if level == "t2":
        return run_e2e(ws, need_batch(ws, arg or batch_of_cwd(ws)))
    die("usage: test t0|t1|t2 [batch]")
