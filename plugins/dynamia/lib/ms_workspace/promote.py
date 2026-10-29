"""Promote: send a repo's base branch to a release branch (qa, main) as a pull request.

    ms-workspace promote [repo] [--to BRANCH] [--yes] [--direct] [--title T] [--body-file F]

Works only on origin's refs, so no checkout or worktree is touched. Without --yes it prints the plan and changes nothing.
The default is a PR from the base branch into the release branch; --direct pushes the base to the release branch instead,
which git only accepts as a fast-forward (never forced). The destination must be listed in the repo's `release = [...]`.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .core import Workspace, die, git_ok, git_out, toplevel
from .release import TYPES, commits

LISTED = 60   # commits named in a PR body; the rest is counted


def _repo(ws: Workspace, name: str) -> str:
    if not name:
        top = toplevel().resolve()
        name = next((r for r in ws.repo_names() if ws.repo_dir(r).resolve() == top), "")
    if name not in ws.repo_names():
        die(f"promote: cannot tell which repo to promote ('{name}'); run it inside the repo or name it: promote <repo>")
    return name


def _destination(ws: Workspace, repo: str, to: str) -> str:
    releases = ws.repo_cfg(repo).get("release") or []
    if not releases:
        die(f"{repo}: no `release = [...]` in workspace.toml, so there is nothing to promote to")
    if to:
        if to not in releases:
            die(f"{repo}: '{to}' is not a release branch of this repo ({', '.join(releases)})")
        return to
    if len(releases) > 1:
        die(f"{repo}: several release branches ({', '.join(releases)}): ask the user which one and pass --to <branch>")
    return releases[0]


def _body(repo: str, base: str, to: str, rows: list[dict], head: str) -> str:
    out = [f"## Summary", "", f"Promotes `{base}` ({head}) to `{to}` in {repo}: {len(rows)} commit(s).", ""]
    if any(c["breaking"] for c in rows):
        out += ["## Breaking changes", ""] + [f"- {c['subject']} ({c['hash']})" for c in rows if c["breaking"]] + [""]
    left = LISTED
    for kind, title in TYPES + [("other", "Other")]:
        group = [c for c in rows if c["kind"] == kind]
        if not group or left <= 0:
            continue
        out += [f"## {title} ({len(group)})", ""] + [f"- {c['text']} ({c['hash']})" for c in group[:left]]
        if len(group) > left:
            out.append(f"- ... and {len(group) - left} more")
        out.append("")
        left -= len(group)
    return "\n".join(out).rstrip() + "\n"


def cmd_promote(ws: Workspace, args: list[str]) -> int:
    yes = direct = False
    to = title = body_file = name = ""
    it = iter(args)
    for a in it:
        if a == "--yes":
            yes = True
        elif a == "--direct":
            direct = True
        elif a in ("--to", "--title", "--body-file"):
            v = next(it, None)
            if v is None:
                die(f"promote: {a} needs a value")
            if a == "--to":
                to = v
            elif a == "--title":
                title = v
            else:
                body_file = v
        elif a.startswith("-"):
            die(f"promote: unknown option {a}")
        elif not name:
            name = a
        else:
            die(f"promote: unexpected argument {a}")

    repo = _repo(ws, name)
    d, base = ws.repo_dir(repo), ws.base(repo)
    to = _destination(ws, repo, to)
    if to == base:
        die(f"{repo}: '{to}' is the base branch; promote goes from the base to a release branch")
    if not git_ok(d, "fetch", "origin", base, to, "--quiet"):
        die(f"{repo}: cannot fetch origin/{base} and origin/{to}; nothing can be verified, so nothing was done")
    src, dst = f"origin/{base}", f"origin/{to}"
    pending = commits(d, dst, src)
    total = int(git_out(d, "rev-list", "--count", f"{dst}..{src}") or 0)
    drift = int(git_out(d, "rev-list", "--count", f"{src}..{dst}") or 0)
    local = int(git_out(d, "rev-list", "--count", f"{src}..{base}") or 0) if git_ok(d, "rev-parse", "--verify", "--quiet", base) else 0
    mode = "direct push" if direct else "PR"

    print(f"Plan: promote {repo} {base} -> {to} ({mode})")
    if total == 0:
        print(f"  {to} is up to date with {base}: nothing to promote.")
        return 0
    print(f"  {total} commit(s) waiting")
    for c in pending[:10]:
        print(f"      {c['hash']} {c['subject'][:90]}")
    if total > 10:
        print(f"      ... and {total - 10} more")
    stat = git_out(d, "diff", "--shortstat", f"{dst}...{src}")
    if stat:
        print(f"      {stat}")
    for c in pending:
        if c["breaking"]:
            print(f"  BREAKING: {c['subject'][:90]}")
    if drift:
        print(f"  WARNING {to} has {drift} commit(s) that {base} does not (hotfix drift)." + (" A direct push would be rejected: use a PR." if direct else " The PR will carry a merge."))
    if local:
        print(f"  WARNING local {base} has {local} commit(s) not pushed to origin; they are NOT part of this promotion.")
    if not yes:
        print("(plan only; pass --yes to " + ("push" if direct else "open the PR") + ")")
        return 0

    head = git_out(d, "rev-parse", "--short", src)
    before = git_out(d, "rev-parse", dst)
    if direct:
        if drift:
            die(f"{repo}: {to} has commits {base} lacks, so a direct push is not a fast-forward; open a PR instead (drop --direct)")
        if subprocess.run(["git", "-C", str(d), "push", "origin", f"refs/remotes/{src}:refs/heads/{to}"]).returncode != 0:
            die(f"{repo}: push to {to} rejected (it moved? run promote again)")
    else:
        if not shutil.which("gh"):
            die(f"{repo}: a pull request needs the GitHub CLI (gh) in PATH; nothing was done")
        body = ""
        if body_file:
            try:
                body = Path(body_file).read_text()
            except OSError as e:
                die(f"promote: cannot read {body_file}: {e}")
        p = subprocess.run(["gh", "pr", "create", "--base", to, "--head", base, "--title", title or f"Promote {base} to {to}",
                            "--body", body or _body(repo, base, to, pending, head)], cwd=d)
        if p.returncode != 0:
            ws.log("promote", "fail", repo, "", f"{base} -> {to}: gh pr create failed")
            die(f"{repo}: the PR could not be opened (does one already exist for {base} -> {to}?); nothing else was changed")
    ws.log("promote", "ok", repo, "", f"{base} -> {to} ({'direct' if direct else 'pr'}, {total} commits)", before=before[:12], after=head)
    print(f"  {repo}: " + (f"{to} now at {head}" if direct else f"PR {base} -> {to} opened") + ". Merging is yours; there is no undo, revert with a PR.")
    return 0
