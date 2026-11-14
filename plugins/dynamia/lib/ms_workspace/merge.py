"""ms-workspace merge <batch>: merge the pull requests a ship opened, once their checks pass, and bring the base branch up to date.

    ms-workspace merge <batch> [--yes] [--wait SECONDS] [--method merge|squash|rebase]

Without --yes it only shows each pull request, its checks and whether it can be merged. With --yes it waits for the
checks (up to --wait seconds, default 600), refuses when one failed, merges with `gh pr merge`, then fetches the base
branch and fast-forwards the repo's own checkout when that is safe (clean and on the base branch). Merging stays a
decision of the user: the guard asks before `--yes`, and agents in a batch cannot call `gh pr merge` by hand."""
from __future__ import annotations

import json
import shutil
import subprocess
import time

import sys

from .core import Workspace, die, git, git_out, need_batch, batch_repos


def eprint(*a):
    print(*a, file=sys.stderr)

METHODS = ("merge", "squash", "rebase")
POLL_SECONDS = 15


def _gh(wt, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], cwd=wt, capture_output=True, text=True)


def find_pr(wt, branch: str) -> dict | None:
    """The newest pull request whose head is `branch` (number, url, state, mergeable), or None."""
    p = _gh(wt, "pr", "list", "--head", branch, "--state", "all", "--limit", "5", "--json", "number,url,state,mergeable")
    if p.returncode != 0:
        die(f"gh could not list pull requests for {branch}: {(p.stderr or p.stdout).strip()[:200]}")
    try:
        rows = json.loads(p.stdout or "[]")
    except ValueError:
        die("gh returned something that is not JSON for 'pr list'")
    open_first = sorted(rows, key=lambda r: (r.get("state") != "OPEN", -int(r.get("number", 0))))
    return open_first[0] if open_first else None


def checks_of(wt, number: int) -> dict:
    """Counts of passing, pending and failing checks of a PR (all zero when it has none)."""
    p = _gh(wt, "pr", "checks", str(number), "--json", "name,bucket")
    try:
        rows = json.loads(p.stdout or "[]")
    except ValueError:
        rows = []
    count = {"pass": 0, "pending": 0, "fail": 0}
    for row in rows:
        bucket = row.get("bucket", "")
        count["fail" if bucket in ("fail", "cancel") else "pending" if bucket == "pending" else "pass"] += 1
    return count


def _sync_base(ws: Workspace, repo: str) -> str:
    base, d = ws.base(repo), ws.repo_dir(repo)
    if git(d, "fetch", "origin", base, "--quiet").returncode != 0:
        return f"could not fetch origin/{base}"
    if git_out(d, "branch", "--show-current") != base:
        return f"{d.name} is not on {base}; not updated"
    if git_out(d, "status", "--porcelain"):
        return f"{d.name} has uncommitted changes; not updated"
    res = git(d, "merge", "--ff-only", f"origin/{base}")
    return f"{base} fast-forwarded to origin/{base}" if res.returncode == 0 else f"{base} could not fast-forward ({res.stderr.strip()[:100]})"


def cmd_merge(ws: Workspace, args: list[str]) -> int:
    yes, wait, method, names, it = False, 600, str(ws.get("ship", "merge_method", default="merge")), [], iter(args)
    for a in it:
        if a == "--yes":
            yes = True
        elif a in ("--wait", "--method"):
            v = next(it, None)
            if v is None:
                die(f"merge: {a} needs a value")
            if a == "--wait":
                if not v.isdigit():
                    die("merge: --wait is a number of seconds")
                wait = int(v)
            else:
                method = v
        elif a.startswith("-"):
            die(f"merge: unknown option {a}")
        else:
            names.append(a)
    if method not in METHODS:
        die(f"merge: --method is one of {', '.join(METHODS)}")
    if not names:
        die("usage: merge <batch> [--yes] [--wait SECONDS] [--method merge|squash|rebase]")
    if not shutil.which("gh"):
        die("merge needs the GitHub CLI (gh) in PATH")
    batch = need_batch(ws, names[0])
    from .batches import int_branch
    plan = []
    for r in batch_repos(ws, batch):
        wt = ws.batch_dir / batch / r
        pr = find_pr(wt, int_branch(ws, batch, r))
        if pr is None:
            print(f"  {r}: no pull request for {int_branch(ws, batch, r)} (ship it with --pr first)")
            continue
        c = checks_of(wt, pr["number"]) if pr["state"] == "OPEN" else {"pass": 0, "pending": 0, "fail": 0}
        print(f"  {r}: PR #{pr['number']} {pr['url']} {pr['state']}" + (f", checks {c['pass']} pass / {c['pending']} pending / {c['fail']} failed, {pr.get('mergeable', '?')}" if pr["state"] == "OPEN" else ""))
        plan.append((r, wt, pr))
    if not plan:
        die(f"batch '{batch}' has no pull request to merge")
    if not yes:
        print("(plan only; pass --yes to wait for the checks, merge and update the base branch)")
        return 0
    for r, wt, pr in plan:
        if pr["state"] == "MERGED":
            print(f"  {r}: PR #{pr['number']} was already merged; {_sync_base(ws, r)}")
            continue
        if pr["state"] != "OPEN":
            die(f"{r}: PR #{pr['number']} is {pr['state']}, not open")
        deadline = time.time() + wait
        while True:
            c = checks_of(wt, pr["number"])
            if c["fail"]:
                die(f"{r}: {c['fail']} check(s) failed on PR #{pr['number']}; nothing was merged ({pr['url']})")
            if not c["pending"]:
                break
            if time.time() >= deadline:
                die(f"{r}: checks are still pending after {wait}s on PR #{pr['number']}; nothing was merged (run again later)")
            eprint(f"  {r}: {c['pending']} check(s) pending, waiting...")
            time.sleep(POLL_SECONDS)
        p = _gh(wt, "pr", "merge", str(pr["number"]), f"--{method}")
        if p.returncode != 0:
            die(f"{r}: gh could not merge PR #{pr['number']}: {(p.stderr or p.stdout).strip()[:200]}")
        ws.log("merge", "ok", r, batch, f"PR #{pr['number']} {method} {pr['url']}")
        print(f"  {r}: merged PR #{pr['number']} ({method}); {_sync_base(ws, r)}")
    print(f"Merged. Cleanup: ms-workspace clean {batch}")
    return 0
