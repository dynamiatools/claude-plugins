"""git-overview: the state of the repo here, or of every repo one level below, in one call. Read-only."""
import os
from pathlib import Path

from mcplib import Tool, ToolFail, run, serve

ROOT = Path(os.environ.get("DYNAMIA_ROOT", os.getcwd())).resolve()


def git(repo: Path, *argv: str) -> str:
    r = run(["git", *argv], cwd=str(repo))
    return r.stdout.strip() if r.returncode == 0 else ""


def repo_row(repo: Path) -> dict:
    counts = git(repo, "rev-list", "--left-right", "--count", "@{upstream}...HEAD").split()
    behind, ahead = (int(counts[0]), int(counts[1])) if len(counts) == 2 else (None, None)
    return {
        "repo": repo.name,
        "branch": git(repo, "branch", "--show-current") or "(detached)",
        "ahead": ahead, "behind": behind,
        "dirty": len([l for l in git(repo, "status", "--porcelain").splitlines() if l]),
        "last": git(repo, "log", "-1", "--format=%h %s")[:90],
    }


def repos_in(root: Path) -> list[Path]:
    if (root / ".git").exists():
        return [root]
    return sorted(p for p in root.iterdir() if p.is_dir() and (p / ".git").exists())


def repos(_: dict):
    found = repos_in(ROOT)
    if not found:
        raise ToolFail("no git repo here or one level below")
    return [repo_row(r) for r in found]


def worktrees(_: dict):
    out = []
    for r in repos_in(ROOT):
        block = {}
        for line in git(r, "worktree", "list", "--porcelain").splitlines() + [""]:
            if line == "":
                if block:
                    out.append({"repo": r.name, "path": block.get("worktree", ""), "branch": block.get("branch", "").removeprefix("refs/heads/")})
                block = {}
            elif " " in line:
                k, v = line.split(" ", 1)
                block[k] = v
    return out


def stashes(_: dict):
    return [{"repo": r.name, "stash": l} for r in repos_in(ROOT) for l in git(r, "stash", "list").splitlines()]


TOOLS = {
    "repos": Tool("Branch, ahead/behind upstream, dirty file count and last commit for the repo here or each repo one level below.", {}, repos),
    "worktrees": Tool("Worktrees of each repo with their branch.", {}, worktrees),
    "stashes": Tool("Stash entries of each repo.", {}, stashes),
}

if __name__ == "__main__":
    serve("git-overview", TOOLS)
