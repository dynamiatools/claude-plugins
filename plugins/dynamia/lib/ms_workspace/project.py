"""Project helpers for workspace-init: detect a repo, keep .dynamia/ out of git, move an older layout.

The workspace lives in <project>/.dynamia/ (workspace.toml plus workspace/ for batches and state); the project
folder keeps CLAUDE.md and the repos themselves. When the project is itself a git repo, .dynamia/ is excluded locally
through .git/info/exclude, so nothing is added to the repo's tracked files.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .core import die
from .claude_md import BEGIN

EXCLUDE_LINE = ".dynamia/"
MOVABLE = ("requests", "mocks")


def _git(cwd: Path, *args: str) -> str | None:
    r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.stdout.strip() if r.returncode == 0 else None


def repo_root(start: Path) -> Path | None:
    top = _git(start, "rev-parse", "--show-toplevel")
    return Path(top) if top else None


def exclude_file(repo: Path) -> Path:
    return Path(_git(repo, "rev-parse", "--path-format=absolute", "--git-path", "info/exclude") or die("not a git repository"))


def is_excluded(repo: Path) -> bool:
    r = subprocess.run(["git", "-C", str(repo), "check-ignore", "-q", ".dynamia/x"], capture_output=True)
    return r.returncode == 0


def cmd_project(args: list[str]) -> int:
    """JSON about a folder: is it inside a repo, is there a workspace, is CLAUDE.md the repo's own."""
    start = Path(args[0] if args else ".").resolve()
    repo = repo_root(start)
    project = repo or start
    md = project / "CLAUDE.md"
    text = md.read_text() if md.is_file() else ""
    layout = "new" if (project / ".dynamia" / "workspace.toml").is_file() else "old" if (project / "workspace.toml").is_file() else "none"
    print(json.dumps({
        "in_repo": repo is not None, "project": str(project), "workspace": layout,
        "claude_md": {"exists": md.is_file(), "managed": BEGIN in text},
        "excluded": is_excluded(repo) if repo else None,
    }, indent=2))
    return 0


def cmd_exclude(args: list[str]) -> int:
    repo = repo_root(Path(args[0] if args else ".").resolve())
    if repo is None:
        die("not inside a git repository; nothing to exclude")
    if is_excluded(repo):
        print(f"present  {EXCLUDE_LINE} is already ignored in {repo}")
        return 0
    target = exclude_file(repo)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = target.read_text() if target.exists() else ""
    target.write_text(text + ("" if not text or text.endswith("\n") else "\n") + EXCLUDE_LINE + "\n")
    print(f"added    {EXCLUDE_LINE} to {target}")
    return 0


def state_moves(old: Path, dest: Path) -> list[tuple[Path, Path]]:
    """Leftovers of the dot folders: the children of .ms-workspace/ go directly into `dest`, .batches/ becomes working-trees/."""
    moves = [(c, dest / c.name) for c in sorted((old / ".ms-workspace").iterdir())] if (old / ".ms-workspace").is_dir() else []
    return moves + ([(old / ".batches", dest / "working-trees")] if (old / ".batches").is_dir() else [])


def plan_migration(root: Path, repos: list[str]) -> list[tuple[Path, Path]]:
    """Older layout (everything in one folder): config and state go into .dynamia/; the repos stay where they are."""
    new = root / ".dynamia"
    moves = [(root / "workspace.toml", new / "workspace.toml")]
    moves += [(root / name, new / "workspace" / name) for name in MOVABLE if (root / name).exists()]
    return moves + state_moves(root, new / "workspace")


def cmd_migrate(args: list[str]) -> int:
    """Bring a workspace to the current layout: an older single-folder one into .dynamia/, clones left in .dynamia/workspace/ out to
    the project folder, and .batches/ + .ms-workspace/ into working-trees/ + logs/, images/, memory/ ... Needs --yes to act."""
    import tomllib
    from .core import find_workspace_root, in_dynamia
    old = find_workspace_root()
    if old is None:
        die("no workspace found here (nothing to migrate)")
    inside = in_dynamia(old)
    cfg = tomllib.loads(((old.parent if inside else old) / "workspace.toml").read_text())
    batches = old / ".batches"
    if batches.is_dir() and any(batches.iterdir()):
        die("there are open batches (git worktrees hold absolute paths); ship or clean them first with ms-workspace clean")
    repos = [r for r, c in (cfg.get("repos") or {}).items() if not (c or {}).get("path")]
    if inside:
        moves = [(old / r, old.parent.parent / r) for r in repos if (old / r / ".git").exists()] + state_moves(old, old)
    else:
        moves = plan_migration(old, repos)
    if not moves:
        die("nothing to migrate: the workspace already has the current layout")
    clash = [str(dst) for _, dst in moves if dst.exists()]
    if clash:
        die("already exists, nothing moved: " + ", ".join(clash))
    for src, dst in moves:
        print(f"{'move' if '--yes' in args else 'would move'}  {src} -> {dst}")
    if "--yes" not in args:
        print("Run again with --yes to apply (nothing needs to be committed or stashed: folders are moved as they are).")
        return 0
    for src, dst in moves:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
    try:
        (old / ".ms-workspace").rmdir()   # emptied above; a leftover file keeps it
    except OSError:
        pass
    print("Done. CLAUDE.md stays in the project folder; run ms-workspace claude-md to refresh its block.")
    return 0
