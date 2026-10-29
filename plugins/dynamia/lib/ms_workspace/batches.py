"""Batch lifecycle: batch new, agent new, env, affected, integrate, ship, clean."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .core import (MsError, Workspace, ahead_of_base, base_ref, batch_of_cwd, batch_repos, changed_files, die, git,
                   git_ok, git_out, modules_of, need_batch, run, toplevel, topo)


def eprint(*a):
    print(*a, file=sys.stderr)


NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def valid_name(kind: str, name: str) -> str:
    if not NAME.match(name or "") or ".." in name:
        die(f"invalid {kind} name '{name}': use letters, digits, '.', '_' and '-' (no slashes, not starting with a symbol)")
    return name


def agent_branches(ws: Workspace, batch: str, repo: str) -> list[str]:
    wt = ws.batch_dir / batch / repo
    return [b for b in git_out(wt, "for-each-ref", "--format=%(refname:short)", f"refs/heads/agent/{batch}/").splitlines() if b]


def unintegrated(ws: Workspace, batch: str, repo: str) -> list[str]:
    """Agent branches of the batch whose commits are not part of int/<batch> yet."""
    wt = ws.batch_dir / batch / repo
    return [b for b in agent_branches(ws, batch, repo) if not git_ok(wt, "merge-base", "--is-ancestor", b, f"int/{batch}")]


# ------------------------------------------------------------ environment files
def copy_env(ws: Workspace, repo: str, dst: Path) -> None:
    """Copy gitignored files a fresh worktree lacks: .worktreeinclude, env_files and settings.local.json."""
    src = ws.repo_dir(repo)
    names = set()
    if (src / ".worktreeinclude").is_file():
        r = git(src, "ls-files", "--others", "--ignored", "--exclude-from=.worktreeinclude")
        names.update(r.stdout.splitlines())
    names.update(ws.repo_cfg(repo).get("env_files") or [])
    names.add(".claude/settings.local.json")
    copied = 0
    for f in sorted(names):
        if not f or f.startswith("/") or ".." in f:
            continue
        if not (src / f).is_file() or (dst / f).exists():
            continue
        if not git_ok(src, "check-ignore", "-q", "--", f):  # never copy tracked files
            continue
        (dst / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src / f, dst / f)
        copied += 1
    if copied:
        print(f"    copied {copied} ignored file(s) into {dst.name}")


def trust_dir(directory: Path) -> None:
    """Mark a directory as trusted so Claude skips the 'trust this folder' dialog (atomic write, symlink-safe)."""
    cfg = Path(os.environ.get("HOME", "~")).expanduser() / ".claude.json"
    if not cfg.is_file():
        return
    real = Path(os.path.realpath(cfg))
    try:
        data = json.loads(real.read_text())
        data.setdefault("projects", {}).setdefault(str(directory), {})["hasTrustDialogAccepted"] = True
        tmp = real.with_name(f"{real.name}.ms-{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data, indent=2))
        shutil.copymode(real, tmp)
        os.replace(tmp, real)
    except (OSError, ValueError):
        pass


def worktree_dirs(ws: Workspace, batch: str) -> list[Path]:
    out = []
    for repo in batch_repos(ws, batch):
        out.append(ws.batch_dir / batch / repo)
        out.extend(sorted((ws.batch_dir / batch / ".agents").glob(f"*/{repo}")))
    return out


def cmd_env(ws: Workspace, args: list[str]) -> int:
    setup = trust = False
    batch = ""
    for a in args:
        if a == "--setup":
            setup = True
        elif a == "--trust":
            trust = True
        else:
            batch = a
    batch = need_batch(ws, batch or batch_of_cwd(ws))
    for d in worktree_dirs(ws, batch):
        repo = d.name
        print(f"  {d}")
        copy_env(ws, repo, d)
        if trust:
            trust_dir(d)
        cmd = ws.repo_cfg(repo).get("setup")
        if setup and cmd:
            print(f"    setup: {cmd}")
            with ws.heavy_lock(1800):
                r = subprocess.run(["bash", "-c", cmd], cwd=d, capture_output=True, text=True, stdin=subprocess.DEVNULL, env=ws.run_env(repo))
            if r.returncode == 0:
                ws.log("env.setup", "ok", repo, batch, cmd)
            else:
                ws.log("env.setup", "fail", repo, batch, cmd)
                eprint(f"    setup FAILED: {cmd}")
                eprint("\n".join("      " + l for l in (r.stdout + r.stderr).splitlines()[-15:]))
    ws.log("env", "ok", "", batch, f"setup={int(setup)} trust={int(trust)}")
    return 0


# ----------------------------------------------------------------------- batch
def _rollback(ws: Workspace, created: list[tuple[str, Path, str]], directory: Path | None) -> None:
    """Undo the worktrees and branches created by a failed command so a rerun starts clean."""
    for repo, wt, branch in reversed(created):
        git(ws.repo_dir(repo), "worktree", "remove", "--force", str(wt))
        git(ws.repo_dir(repo), "branch", "-D", branch)
    if directory is not None:
        shutil.rmtree(directory, ignore_errors=True)


def cmd_batch(ws: Workspace, args: list[str]) -> int:
    if not args or args[0] != "new" or len(args) < 2:
        die("usage: batch new <name> [repo...]")
    name, repos = valid_name("batch", args[1]), args[2:] or ws.repo_names()
    directory = ws.batch_dir / name
    if directory.exists():
        die(f"batch '{name}' already exists at {directory}")
    directory.mkdir(parents=True)
    created: list[tuple[str, Path, str]] = []
    try:
        for r in repos:
            src, base = ws.repo_dir(r), ws.base(r)
            if r not in ws.repo_names() or not (src / ".git").exists():
                ws.log("batch.new", "error", r, name, f"repo not found at {src}")
                die(f"repo '{r}' not found at {src}")
            if not git_ok(src, "fetch", "origin", base, "--quiet"):
                eprint(f"warn: could not fetch {r}/{base} (using local ref)")
            start = f"origin/{base}" if git_ok(src, "rev-parse", "--verify", "--quiet", f"origin/{base}") else base
            res = git(src, "worktree", "add", "--no-track", "-b", f"int/{name}", str(directory / r), start)
            if res.returncode != 0:
                ws.log("batch.new", "error", r, name, "worktree add failed")
                die(f"could not create worktree for {r} (branch int/{name} may exist): {res.stderr.strip()}")
            created.append((r, directory / r, f"int/{name}"))
            ws.log("batch.new", "ok", r, name, f"int/{name} from {start}")
            print(f"  {r} -> {directory / r} (int/{name} from {start})")
            copy_env(ws, r, directory / r)
    except MsError:
        _rollback(ws, created, directory)
        raise
    lines = [f"# Batch: {name}", "", f"Repos: {' '.join(repos)}", "", "## Tasks"]
    for r in repos:
        if ws.task_mode(r) == "github":
            lines.append(f"- {r}: tracked in GitHub issues; list only issue numbers here")
        else:
            lines.append(f"- [ ] {r}: ")
    (directory / "TASKS.md").write_text("\n".join(lines) + "\n")
    print(f"Batch ready: {directory}")
    return 0


def cmd_agent(ws: Workspace, args: list[str]) -> int:
    if len(args) < 3 or args[0] != "new":
        die("usage: agent new <batch> <task> [repo...]")
    batch = need_batch(ws, args[1])
    task = valid_name("task", args[2])
    repos = args[3:] or batch_repos(ws, batch)
    created: list[tuple[str, Path, str]] = []
    try:
        for r in repos:
            main_wt = ws.batch_dir / batch / r
            wt = ws.batch_dir / batch / ".agents" / task / r
            if not main_wt.is_dir():
                die(f"repo '{r}' is not part of batch '{batch}'")
            res = git(main_wt, "worktree", "add", "--no-track", "-b", f"agent/{batch}/{task}", str(wt), f"int/{batch}")
            if res.returncode != 0:
                die(f"could not create agent worktree for {r} (branch agent/{batch}/{task} may exist): {res.stderr.strip()}")
            created.append((r, wt, f"agent/{batch}/{task}"))
            ws.log("agent.new", "ok", r, batch, f"agent/{batch}/{task}")
            print(f"  {r} -> {wt} (agent/{batch}/{task})")
            copy_env(ws, r, wt)
    except MsError:
        _rollback(ws, created, None)
        shutil.rmtree(ws.batch_dir / batch / ".agents" / task, ignore_errors=True)
        raise
    return 0


# -------------------------------------------------------------------- affected
def cmd_affected(ws: Workspace, args: list[str]) -> int:
    top = toplevel()
    repo, base = top.name, ws.base(top.name)
    files = changed_files(top, base)
    dependents: set[str] = set()
    grew = True
    while grew:  # transitive closure of "depends on <repo>"
        grew = False
        for r in ws.repo_names():
            if r != repo and r not in dependents and any(d == repo or d in dependents for d in ws.deps(r)):
                dependents.add(r)
                grew = True
    mods = modules_of(top, files)
    out = {"repo": repo, "files": len(files), "modules": mods, "dependents": sorted(dependents)}
    if (top / "pom.xml").is_file():
        from .modules import closure, load_reactor
        out["closure"] = closure(load_reactor(top), set(mods))   # changed modules plus every module that depends on them
    print(json.dumps(out, separators=(",", ":")))
    return 0


# ------------------------------------------------------------------- integrate
def cmd_integrate(ws: Workspace, args: list[str]) -> int:
    if not args:
        die("usage: integrate <batch> [--dry-run]")
    batch = need_batch(ws, args[0])
    unknown = [a for a in args[1:] if a != "--dry-run"]
    if unknown:
        die(f"integrate: unknown option {unknown[0]}")
    dry = "--dry-run" in args[1:]
    conflict = False
    for r in topo(ws, batch_repos(ws, batch)):
        wt = ws.batch_dir / batch / r
        if not dry and git_out(wt, "status", "--porcelain"):
            die(f"{r}: int/{batch} worktree has uncommitted changes")
        branches = git_out(wt, "for-each-ref", "--format=%(refname:short)", f"refs/heads/agent/{batch}/").splitlines()
        for br in branches:
            if git_ok(wt, "merge-base", "--is-ancestor", br, "HEAD"):
                print(f"  {r}: {br} already merged")
                continue
            mt = git(wt, "merge-tree", "--write-tree", "--name-only", "HEAD", br)
            if mt.returncode == 0:
                if dry:
                    print(f"  {r}: {br} merges cleanly")
                else:
                    m = git(wt, "merge", "--no-ff", "--no-edit", "-m", f"Integrate {br}", br)
                    if m.returncode != 0:
                        die(f"{r}: merging {br} failed: {m.stderr.strip()}")
                    ws.log("integrate", "ok", r, batch, br)
                    print(f"  {r}: merged {br}")
            else:
                lines = mt.stdout.splitlines()[1:]
                files = " ".join(l for l in (lines[: lines.index("")] if "" in lines else lines) if l)
                eprint(f"  {r}: CONFLICT merging {br} -> {files}")
                ws.log("integrate", "conflict", r, batch, f"{br}: {files}")
                conflict = True
    if conflict:
        eprint(f"Resolve the conflicts (rebase the agent branch on int/{batch}), then run again.")
        return 1
    if not dry:
        print(f"Integrated. Next: ms-workspace test t1 {batch}")
    return 0


# ------------------------------------------------------------------------ ship
def cmd_ship(ws: Workspace, args: list[str]) -> int:
    """ship, plus an optional notification ([notify] on = ["ship"]) when a real run finishes or fails."""
    from .notify import notify_event
    real = "--yes" in args and bool(args)
    try:
        code = _ship(ws, args)
    except MsError as e:
        if real:
            notify_event(ws, "ship", "Ship failed", f"batch {args[0]}: {e}", "high")
        raise
    if real and getattr(ws, "_shipped", None):
        notify_event(ws, "ship", "Shipped", f"batch {args[0]} pushed: {', '.join(ws._shipped)}")
    return code


def push_mode(ws: Workspace, repo: str, force_pr: bool = False, force_direct: bool = False) -> str:
    """How a repo is published: its configured `push` ("direct" by default), or what this run asks for (--pr, --direct).
    `push = "ask"` has no answer of its own: the run must say --pr or --direct, so the agent asks the user first."""
    if force_pr:
        return "pr"
    if force_direct:
        return "direct"
    mode = ws.repo_cfg(repo).get("push") or "direct"
    if mode == "ask":
        die(f"{repo}: push = \"ask\": ask the user whether to open a PR or push directly, then run again with --pr or --direct")
    return mode


PR_HINT_DEFAULTS = {"files": 20, "lines": 800, "new_files": 10}


def pr_recommendation(ws: Workspace, wt: Path, ref: str) -> str:
    """Why a big change is better reviewed as a PR ('' when it is small). Only advice: ship never switches mode by itself.
    Limits come from [ship] recommend_pr_files / recommend_pr_lines / recommend_pr_new_files (0 turns one off)."""
    limits = {k: int(ws.get("ship", f"recommend_pr_{k}", default=v)) for k, v in PR_HINT_DEFAULTS.items()}
    files = lines = 0
    for row in git_out(wt, "diff", "--numstat", f"{ref}...HEAD").splitlines():
        added, _, rest = row.partition("\t")
        deleted = rest.partition("\t")[0]
        files += 1
        lines += int(added) + int(deleted) if added.isdigit() and deleted.isdigit() else 0
    new = len(git_out(wt, "diff", "--name-only", "--diff-filter=A", f"{ref}...HEAD").splitlines())
    found = [f"{n} {label} (limit {limits[k]})" for k, n, label in (("files", files, "files changed"), ("lines", lines, "lines changed"), ("new_files", new, "new files"))
             if limits[k] and n >= limits[k]]
    return ", ".join(found)


def pr_text(wt: Path, base: str, batch: str, title: str, body: str, checks: str) -> tuple[str, str]:
    """Title and body for a PR. Explicit --title/--body-file win; otherwise build them from the commits."""
    ref = base_ref(wt, base)
    subjects = git_out(wt, "log", "--reverse", "--no-merges", "--format=%s", f"{ref}..HEAD").splitlines()
    if not title:
        title = subjects[0] if len(subjects) == 1 else (f"{subjects[0]} (+{len(subjects) - 1} more)" if subjects else batch)
    if not body:
        commits = git_out(wt, "log", "--reverse", "--no-merges", "--format=- %s%n%w(0,2,2)%b", f"{ref}..HEAD").strip()
        stat = git_out(wt, "diff", "--stat", f"{ref}...HEAD")
        body = (f"## Summary\n\n{commits}\n\n## Changes\n\n```\n{stat}\n```\n\n"
                f"## Verification\n\n{checks}\n\nBatch: `{batch}`")
    return title, body


def _plain_target(ws: Workspace, repo: str) -> tuple[str, dict]:
    """The plain local branch checked out in a repo's own checkout: (record label, {repo: (checkout, branch)}).
    The repo is the argument, else the one the current directory belongs to."""
    name = repo
    if not name:
        top = toplevel()
        name = next((r for r in ws.repo_names() if ws.repo_dir(r).resolve() == top.resolve()), "")
    if name not in ws.repo_names():
        die(f"ship --branch: cannot tell which repo to ship ('{name or repo}'); run it inside the repo or name it: ship --branch <repo>")
    directory = ws.repo_dir(name)
    branch = git_out(directory, "branch", "--show-current")
    if not branch or branch == ws.base(name):
        die(f"{name}: ship --branch needs a task branch checked out, not '{branch or 'a detached HEAD'}' (base is '{ws.base(name)}')")
    return "branch-" + branch.replace("/", "-"), {name: (directory, branch)}


def _ship(ws: Workspace, args: list[str]) -> int:
    from .runner import run_e2e, test_t1

    if not args:
        die("usage: ship <batch>|--branch [<repo>] [--yes] [--pr|--direct] [--skip-e2e] [--title T] [--body-file F]")
    plain = args[0] == "--branch"   # a plain local branch in the repo's own checkout, no int/<batch> worktree
    if plain:
        repo_arg = args[1] if len(args) > 1 and not args[1].startswith("-") else ""
        args = args[(2 if repo_arg else 1):]
        batch, place = _plain_target(ws, repo_arg)
        args = [batch] + args   # from here on args[0] stands for the batch, as in a normal ship
    else:
        batch = need_batch(ws, args[0])
        place = {r: (ws.batch_dir / batch / r, f"int/{batch}") for r in batch_repos(ws, batch)}
    yes = skip_e2e = skip_smoke = skip_gate = force_pr = force_direct = False
    pr_title = pr_body = ""
    rest = iter(args[1:])
    for a in rest:
        if a == "--yes":
            yes = True
        elif a in ("--title", "--body-file"):
            v = next(rest, None)
            if v is None:
                die(f"ship: {a} needs a value")
            if a == "--title":
                pr_title = v
            else:
                try:
                    pr_body = Path(v).read_text()
                except OSError as e:
                    die(f"ship: cannot read {v}: {e}")
        elif a == "--pr":
            force_pr = True
        elif a == "--direct":
            force_direct = True
        elif a == "--skip-e2e":
            skip_e2e = True
        elif a == "--skip-smoke":
            skip_smoke = True
        elif a == "--skip-gate":
            skip_gate = True
        else:
            die(f"ship: unknown option {a}")

    repos = []
    for r in topo(ws, list(place)):
        wt, base = place[r][0], ws.base(r)
        if git_out(wt, "status", "--porcelain"):
            die(f"{r}: uncommitted changes in {place[r][1]}")
        pending = [] if plain else unintegrated(ws, batch, r)
        if pending:
            die(f"{r}: agent branches not integrated into int/{batch}: {', '.join(pending)}; "
                f"run 'ms-workspace integrate {batch}' first (or 'clean --force' to discard them)")
        if base in (ws.repo_cfg(r).get("release") or []):
            die(f"{r}: base '{base}' is a release branch; ship never targets those; use 'ms-workspace promote' to move a base branch to it")
        if push_mode(ws, r, force_pr, force_direct) == "pr" and not shutil.which("gh"):
            die(f"{r}: a pull request needs the GitHub CLI (gh) in PATH; nothing was pushed")
        if not git_ok(ws.repo_dir(r), "fetch", "origin", base, "--quiet"):
            eprint(f"warn: could not fetch {r}/{base}")
        if ahead_of_base(wt, base) == 0:
            print(f"skip {r} (nothing to ship)")
            continue
        repos.append(r)
    if not repos:
        print(f"Nothing to ship in batch '{batch}'.")
        return 0

    print(f"Plan for batch '{batch}' (this is what would be sent):")
    for r in repos:
        wt, base = place[r][0], ws.base(r)
        mode = push_mode(ws, r, force_pr, force_direct)
        ref = base_ref(wt, base)
        n = ahead_of_base(wt, base)
        print(f"  {r}: {place[r][1]} -> {base} ({mode}, {n} commits)")
        for l in git_out(wt, "log", "--format=%h %s", "--max-count=10", f"{ref}..HEAD").splitlines():
            print(f"      {l}")
        if n > 10:
            print(f"      ... and {n - 10} more")
        stat = git_out(wt, "diff", "--shortstat", f"{ref}...HEAD")
        if stat:
            print(f"      {stat}")
        why = pr_recommendation(ws, wt, ref) if mode != "pr" else ""
        if why:
            print(f"      RECOMMEND A PR: {why}. A direct push sends it all to {base} at once; to open a PR instead: ms-workspace ship {batch} --pr")
    from .gate import gate_places, report
    gate_lines, gate_blocks, gate_warns = report(gate_places(ws, place))
    print("  gate: " + ("clean" if not gate_blocks and not gate_warns else f"{gate_blocks} blocking, {gate_warns} warning(s)") + ("  [skipped by --skip-gate]" if skip_gate else ""))
    print("\n".join(gate_lines))
    smoke = ws.get("http", "smoke")
    if smoke:
        print(f"  smoke checks: {smoke} (env {ws.get('http', 'smoke_env', default='local')}) before the push" + ("  [skipped by --skip-smoke]" if skip_smoke else ""))
    if not yes:
        print("(plan only; pass --yes to run: sync, t1, smoke checks, e2e, push)")
        return 0

    # 1) sync with the base branch (merge, since int/* is local only)
    for r in repos:
        wt, base = place[r][0], ws.base(r)
        if not git_ok(wt, "merge-base", "--is-ancestor", f"origin/{base}", "HEAD"):
            print(f"  {r}: base moved, merging origin/{base}")
            if not git_ok(wt, "merge", "--no-edit", f"origin/{base}"):
                git(wt, "merge", "--abort")
                ws.log("ship", "conflict", r, batch, f"merging origin/{base}")
                die(f"{r}: conflict merging origin/{base} into {place[r][1]}; resolve it in {wt} and run ship again")
    # 2) gate and tests
    if gate_blocks and not skip_gate:
        ws.log("ship", "fail", "", batch, f"gate: {gate_blocks} blocking finding(s)")
        die(f"the gate found {gate_blocks} blocking problem(s) in what would be sent (listed above); nothing was pushed. Fix them or pass --skip-gate")
    if test_t1(ws, batch, place) != 0:
        ws.log("ship", "fail", "", batch, "t1 failed")
        die("t1 failed; nothing was pushed")
    if smoke and not skip_smoke:
        from .apitest import run_file
        print("  smoke checks:")
        if run_file(ws, smoke, ws.get("http", "smoke_env", default="local"), assume_yes=True) != 0:
            ws.log("ship", "fail", "", batch, "smoke checks failed")
            die("smoke checks failed; nothing was pushed (fix them, or pass --skip-smoke)")
    if not skip_e2e:
        if not ws.get("e2e", "command"):
            die("no [e2e] command configured; pass --skip-e2e to ship without e2e")
        if run_e2e(ws, "" if plain else batch) != 0:
            ws.log("ship", "fail", "", batch, "t2 failed")
            die("e2e failed; nothing was pushed")
    # 3) push. Record what the base branch pointed to before and after, so the ship can be undone.
    stamp = time.strftime("%Y%m%d-%H%M%S")
    record_path = ws.state_dir / "ship" / f"{batch}-{stamp}.json"
    record = {"batch": batch, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "repos": {}}
    for r in repos:
        wt, base = place[r][0], ws.base(r)
        record["repos"][r] = {"base": base, "mode": push_mode(ws, r, force_pr, force_direct), "branch": place[r][1],
                              "before": git_out(wt, "rev-parse", f"origin/{base}"), "after": git_out(wt, "rev-parse", "HEAD"), "pushed": False}
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(json.dumps(record, indent=2))
    for r in repos:
        wt, base = place[r][0], ws.base(r)
        mode = push_mode(ws, r, force_pr, force_direct)
        if mode == "pr":
            p = subprocess.run(["git", "-C", str(wt), "push", "origin", place[r][1]])
            if p.returncode != 0:
                die(f"{r}: could not push {place[r][1]}")
            checks = "- Unit tests (t1): passed" + ("" if skip_e2e else "\n- End-to-end: passed") + ("\n- Smoke checks: passed" if smoke and not skip_smoke else "")
            title, body = pr_text(wt, base, batch, pr_title, pr_body, checks)
            try:
                p = subprocess.run(["gh", "pr", "create", "--base", base, "--head", place[r][1], "--title", title, "--body", body], cwd=wt)
            except OSError as e:
                die(f"{r}: {place[r][1]} was pushed but 'gh' failed to start ({e}); open the PR by hand")
            if p.returncode != 0:
                die(f"{r}: {place[r][1]} was pushed but the PR could not be opened; open it by hand (or rerun ship after fixing gh)")
        else:
            p = subprocess.run(["git", "-C", str(wt), "push", "origin", f"{place[r][1]}:{base}"])
            if p.returncode != 0:
                die(f"{r}: push to {base} rejected (base moved again? run ship again)")
        record["repos"][r]["pushed"] = True
        record_path.write_text(json.dumps(record, indent=2))
        ws.log("ship", "ok", r, batch, f"{place[r][1]} -> {base} ({mode})",
               before=record["repos"][r]["before"][:12], after=record["repos"][r]["after"][:12])
        print(f"  pushed {r}")
    ws._shipped = list(repos)
    print(f"Shipped. " + ("The branch stays in your checkout; delete it when merged. " if plain else f"Cleanup: ms-workspace clean {batch}. ") + f"To revert: ms-workspace undo {batch}")
    return 0


# ------------------------------------------------------------------------ clean
def _merged(ws: Workspace, batch: str, repo: str, fetch: bool = False) -> bool:
    """The work of int/<batch> is in the base branch as the remote has it, and every agent branch is part of int/<batch>.
    Plain, rebase and squash merges all count: a merge of HEAD into the base that changes nothing means its content is already there."""
    wt = ws.batch_dir / batch / repo
    base = ws.base(repo)
    if fetch and git_ok(ws.repo_dir(repo), "remote", "get-url", "origin") and not git_ok(ws.repo_dir(repo), "fetch", "origin", base, "--quiet"):
        return False  # origin exists but cannot be reached: the merge cannot be verified
    if unintegrated(ws, batch, repo):
        return False
    ref = base_ref(wt, base)
    if git_ok(wt, "merge-base", "--is-ancestor", "HEAD", ref):
        return True
    merged = git(wt, "merge-tree", "--write-tree", ref, "HEAD")
    return merged.returncode == 0 and merged.stdout.strip().splitlines()[0] == git_out(wt, "rev-parse", f"{ref}^{{tree}}")


def cmd_clean(ws: Workspace, args: list[str]) -> int:
    force = "--force" in args
    names = [a for a in args if a != "--force"]
    if not names:
        if not ws.batch_dir.is_dir():
            print("(no batches)")
            return 0
        for b in sorted(p.name for p in ws.batch_dir.iterdir() if p.is_dir()):
            loose = [x for r in batch_repos(ws, b) for x in unintegrated(ws, b, r)]
            ok = all(_merged(ws, b, r) for r in batch_repos(ws, b))
            print(f"{b}: {'merged (safe to clean)' if ok else 'pending'}"
                  + (f" (agent branches not integrated: {', '.join(loose)})" if loose else ""))
        return 0
    batch = need_batch(ws, names[-1])
    repos = batch_repos(ws, batch)
    if not force:
        for r in repos:
            pending = unintegrated(ws, batch, r)
            if pending:
                die(f"{r}: agent branches not integrated into int/{batch}: {', '.join(pending)} (integrate them, or use --force to discard)")
            if not _merged(ws, batch, r, fetch=True):
                die(f"{r}: int/{batch} is not in origin/{ws.base(r)} yet (PR still open or not merged, or origin unreachable). "
                    f"Nothing was removed; use --force to discard the batch anyway")
    from .procs import procs_in_dir
    running = procs_in_dir(ws.batch_dir / batch)
    if running:
        listing = "; ".join(f"{pid} ({cmd})" for pid, cmd in running[:5])
        if not force:
            die(f"processes are still running inside the batch: {listing}. Stop them (ms-workspace ps kill <pid> --yes) or use --force")
        eprint(f"warning: removing the batch while these processes run in it: {listing}")
    flags = ["--force"] if force else []
    for r in repos:
        main_wt = ws.batch_dir / batch / r
        for wt in sorted((ws.batch_dir / batch / ".agents").glob(f"*/{r}")):
            res = git(main_wt, "worktree", "remove", *flags, str(wt))
            if res.returncode != 0:
                die(f"{r}: could not remove {wt}: {res.stderr.strip()}")
        res = git(main_wt, "worktree", "remove", *flags, str(main_wt))
        if res.returncode != 0:
            die(f"{r}: could not remove {main_wt}: {res.stderr.strip()}")
        refs = git_out(ws.repo_dir(r), "for-each-ref", "--format=%(refname:short)", f"refs/heads/agent/{batch}/", f"refs/heads/int/{batch}")
        for b in refs.splitlines():
            git(ws.repo_dir(r), "branch", "-D", b)
        ws.log("clean", "ok", r, batch, "")
        print(f"  cleaned {r}")
    from .memory import drop_batch_handoffs
    drop_batch_handoffs(ws, batch)
    (ws.batch_dir / batch / "TASKS.md").unlink(missing_ok=True)
    # Only empty directories (such as .agents/<task>) are left; remove bottom-up.
    for p in sorted((ws.batch_dir / batch).rglob("*"), key=lambda x: len(x.parts), reverse=True):
        if p.is_dir() and not any(p.iterdir()):
            p.rmdir()
    try:
        (ws.batch_dir / batch).rmdir()
    except OSError:
        pass
    return 0


# ------------------------------------------------------------------------- undo
def cmd_undo(ws: Workspace, args: list[str]) -> int:
    """Revert the last ship of a batch by adding a commit that restores the previous tree (no force-push)."""
    yes = "--yes" in args
    names = [a for a in args if a != "--yes"]
    if not names:
        die("usage: undo <batch> [--yes]")
    records = sorted((ws.state_dir / "ship").glob(f"{valid_name('batch', names[0])}-*.json")) if (ws.state_dir / "ship").is_dir() else []
    if not records:
        die(f"no ship record for batch '{names[0]}' (nothing was shipped from this workspace)")
    record = json.loads(records[-1].read_text())
    batch, failed = record["batch"], False
    print(f"Undo of the ship of '{batch}' made at {record['ts']}:")
    for r in reversed(topo(ws, list(record["repos"]))):
        info, repo_dir = record["repos"][r], ws.repo_dir(r)
        base, before, after = info["base"], info["before"], info["after"]
        if not info["pushed"]:
            print(f"  {r}: was not pushed, nothing to undo")
            continue
        if info["mode"] == "pr":
            print(f"  {r}: pr mode. The base branch was not touched. Close the pull request and delete the branch:")
            print(f"      gh pr close --delete-branch {info['branch']}   (run it inside {repo_dir})")
            continue
        if not git_ok(repo_dir, "fetch", "origin", base, "--quiet"):
            eprint(f"  {r}: could not fetch origin/{base}; check the network and try again")
            failed = True
            continue
        current = git_out(repo_dir, "rev-parse", f"origin/{base}")
        if current == after:
            tree = git_out(repo_dir, "rev-parse", f"{before}^{{tree}}")
            print(f"  {r}: {base} is still at {after[:8]}; a new commit will restore the tree of {before[:8]} (history is kept, no force-push)")
            if not yes:
                continue
            made = git(repo_dir, "commit-tree", tree, "-p", current, "-m", f"Revert batch {batch} (restores {before[:8]})")
            if made.returncode != 0:
                eprint(f"  {r}: could not create the revert commit: {made.stderr.strip()}")
                failed = True
                continue
            pushed = git(repo_dir, "push", "origin", f"{made.stdout.strip()}:refs/heads/{base}")
            if pushed.returncode != 0:
                eprint(f"  {r}: push rejected ({pushed.stderr.strip().splitlines()[-1] if pushed.stderr.strip() else 'unknown'}); nothing changed")
                failed = True
                continue
            ws.log("undo", "ok", r, batch, f"{base}: {after[:8]} -> revert commit {made.stdout.strip()[:8]}")
            print(f"  {r}: reverted on {base}")
        elif git_ok(repo_dir, "merge-base", "--is-ancestor", after, current):
            ahead = git_out(repo_dir, "rev-list", "--count", f"{after}..{current}")
            print(f"  {r}: others pushed {ahead} commit(s) to {base} after this ship; restoring the old tree would erase their work, so nothing is done automatically.")
            print("      Revert only this batch's commits, newest first (from a clean checkout of the base branch):")
            for sha in reversed(git_out(repo_dir, "rev-list", "--first-parent", "--reverse", f"{before}..{after}").split()):
                merge = len(git_out(repo_dir, "rev-list", "--parents", "-n", "1", sha).split()) > 2
                print(f"      git revert --no-edit{' -m 1' if merge else ''} {sha}")
            failed = True
        else:
            print(f"  {r}: {base} no longer contains the shipped commits (history was rewritten); handle it by hand.")
            failed = True
    if not yes:
        print("(plan only; pass --yes to push the revert commits)")
    return 1 if failed else 0
