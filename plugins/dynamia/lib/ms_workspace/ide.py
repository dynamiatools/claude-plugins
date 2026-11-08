"""Open a batch in VS Code or IntelliJ IDEA. Read-only for Git: it never touches branches, commits or remotes.

    ms-workspace open <batch> [--ide code|idea] [--repo R] [--agent TASK] [--dry-run]

What gets opened (the real worktree paths under working-trees/<batch>/):
    default        the batch's worktrees, one per repo
    --agent TASK   the worktrees of that agent (working-trees/<batch>/.agents/<TASK>/<repo>)
    --repo R       only that repo (repeatable)

VS Code: one generated <workspace>/ide/<batch>[--<task>].code-workspace listing the folders, so search,
    git and the window title only ever see that batch. It lives outside every repo, is rewritten only when it changes,
    and opening it again focuses the same window.
IntelliJ: IDEA opens one directory per project and only recognizes Maven/Gradle modules from that directory's own
    pom.xml/build.gradle, so each worktree is opened as its own project (one window per repo; use --repo to open one).
    IDEA creates .idea/ inside the worktree: ignore it in the repo, otherwise `ship` sees uncommitted changes.

workspace.toml (all optional):
    [ide]
    default = "code"                       # used when --ide is not given; otherwise the first IDE found
    code = "/opt/vscode/bin/code"          # executable or command (arguments allowed) instead of searching PATH
    idea = "/opt/idea/bin/idea.sh"
"""
from __future__ import annotations

import json
import shlex
import shutil
import subprocess
from pathlib import Path

from .batches import valid_name
from .core import Workspace, batch_of_cwd, batch_repos, die, git_ok, need_batch

# Launchers searched on PATH when [ide] has no explicit command; the Toolbox folder is where JetBrains puts its scripts.
CANDIDATES = {
    "code": ["code", "codium"],
    "idea": ["idea", "idea.sh", "intellij-idea-ultimate", "intellij-idea-community", "idea-community"],
}
TOOLBOX = Path("~/.local/share/JetBrains/Toolbox/scripts").expanduser()


def find_ide(ws: Workspace, ide: str) -> list[str] | None:
    """Command (as an argv prefix) that launches the IDE, from [ide] or from PATH; None when it is not installed."""
    configured = ws.get("ide", ide, default="")
    if configured:
        argv = shlex.split(configured)
        return argv if argv and shutil.which(argv[0]) else None
    for name in CANDIDATES[ide]:
        found = shutil.which(name) or shutil.which(name, path=str(TOOLBOX))
        if found:
            return [found]
    return None


def pick_ide(ws: Workspace, wanted: str) -> tuple[str, list[str]]:
    if wanted and wanted not in CANDIDATES:
        die(f"unknown IDE '{wanted}' (use: {', '.join(CANDIDATES)})")
    order = [wanted] if wanted else [ws.get("ide", "default", default="")] + list(CANDIDATES)
    for ide in dict.fromkeys(i for i in order if i in CANDIDATES):
        argv = find_ide(ws, ide)
        if argv:
            return ide, argv
        if wanted:
            hint = f"[ide] {ide} in workspace.toml" if ws.get("ide", ide) else f"{' / '.join(CANDIDATES[ide])} on PATH"
            die(f"{ide} not found: install it, put it on PATH, or set {hint}")
    die("no IDE found (looked for " + ", ".join(c for names in CANDIDATES.values() for c in names) + "); set [ide] in workspace.toml")


def targets(ws: Workspace, batch: str, task: str, repos: list[str]) -> list[Path]:
    """Worktree directories to open, in the batch's repo order."""
    base = ws.batch_dir / batch
    if task:
        valid_name("agent", task)
        agent_dir = base / ".agents" / task
        if not agent_dir.is_dir():
            known = sorted(p.name for p in (base / ".agents").glob("*") if p.is_dir())
            die(f"unknown agent '{task}' in batch '{batch}'" + (f" (known: {', '.join(known)})" if known else " (no agent worktrees yet)"))
        base = agent_dir
    available = [r for r in batch_repos(ws, batch) if (base / r).is_dir()]
    for r in repos:
        if r not in available:
            die(f"repo '{r}' has no worktree here (available: {', '.join(available) or 'none'})")
    chosen = [r for r in available if not repos or r in repos]
    if not chosen:
        die(f"nothing to open in batch '{batch}'")
    return [base / r for r in chosen]


def code_workspace_path(ws: Workspace, batch: str, task: str) -> Path:
    return (ws.state_dir / "ide" / (f"{batch}--{task}" if task else batch)).with_suffix(".code-workspace")


def write_code_workspace(ws: Workspace, batch: str, task: str, dirs: list[Path]) -> Path:
    """The .code-workspace for this batch (and agent). Rewritten only when its content changes."""
    label = f"{batch}/{task}" if task else batch
    data = {
        "folders": [{"name": f"{d.name} ({label})", "path": str(d)} for d in dirs],
        "settings": {"window.title": f"{label} · ${{activeEditorShort}}${{separator}}${{rootName}}"},
    }
    path = code_workspace_path(ws, batch, task)
    text = json.dumps(data, indent=2) + "\n"
    if not path.is_file() or path.read_text() != text:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return path


def launch(argv: list[str]) -> None:
    """Start the IDE detached; report it if the launcher fails straight away (a running IDE just keeps going)."""
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                start_new_session=True, text=True)
    except OSError as e:
        die(f"could not start {argv[0]}: {e}")
    try:
        _, err = proc.communicate(timeout=3)
    except subprocess.TimeoutExpired:
        return
    if proc.returncode:
        die(f"{argv[0]} exited with {proc.returncode}: {(err or '').strip()[:300]}")


def cmd_open(ws: Workspace, args: list[str]) -> int:
    ide = task = batch = ""
    repos: list[str] = []
    dry = False
    it = iter(args)
    for a in it:
        if a in ("--ide", "--agent", "--repo"):
            value = next(it, "")
            if not value or value.startswith("-"):
                die(f"{a} needs a value")
            if a == "--ide":
                ide = value
            elif a == "--agent":
                task = value
            else:
                repos.append(value)
        elif a == "--dry-run":
            dry = True
        elif a.startswith("-"):
            die(f"unknown option {a} (usage: open <batch> [--ide code|idea] [--repo R] [--agent TASK] [--dry-run])")
        else:
            batch = a
    batch = batch or batch_of_cwd(ws)
    if batch:
        valid_name("batch", batch)
    batch = need_batch(ws, batch)
    dirs = targets(ws, batch, task, repos)
    ide, argv = pick_ide(ws, ide)

    if ide == "code":
        file = code_workspace_path(ws, batch, task) if dry else write_code_workspace(ws, batch, task, dirs)
        launches = [argv + [str(file)]]
    else:
        launches = [argv + [str(d)] for d in dirs]
        for d in dirs:
            if not git_ok(d, "check-ignore", "-q", ".idea/x"):
                print(f"  note: {d.name} does not ignore .idea/; IDEA will create it and `ship` will see it as uncommitted")

    for cmd in launches:
        print(("would run: " if dry else "opening: ") + " ".join(shlex.quote(c) for c in cmd))
        if not dry:
            launch(cmd)
    if not dry:
        ws.log("open", "ok", "", batch, f"{ide}{' ' + task if task else ''} {','.join(d.name for d in dirs)}")
    return 0
