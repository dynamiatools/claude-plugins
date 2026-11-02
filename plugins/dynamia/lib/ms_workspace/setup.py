"""Merge (or remove) the ms-* hooks, status line and permission into a Claude Code settings.json."""
from __future__ import annotations

import copy
import json
import os
import shutil
import time
from pathlib import Path

from .core import die

LEGACY_ALLOW = ["Bash(ms-workspace:*)"]  # earlier, too broad rule: it auto-approved ship, clean and env
SOURCE = Path(__file__).resolve().parents[2] / "settings" / "hooks.example.json"


def settings_path(project: bool = False) -> Path:
    if project:
        return Path.cwd() / ".claude" / "settings.json"
    return Path(os.environ.get("CLAUDE_HOME") or Path(os.environ.get("HOME", "~")).expanduser() / ".claude") / "settings.json"


def our_commands(src: dict) -> set[str]:
    return {h["command"] for groups in src.get("hooks", {}).values() for g in groups for h in g.get("hooks", [])}


def installed_commands(settings: dict) -> set[str]:
    return {h.get("command", "") for groups in settings.get("hooks", {}).values() for g in groups for h in g.get("hooks", [])}


def merge(settings: dict, src: dict) -> list[str]:
    """Add what is missing; never touch other entries. Returns a human-readable report."""
    report = []
    hooks = settings.setdefault("hooks", {})
    for event, groups in src.get("hooks", {}).items():
        target = hooks.setdefault(event, [])
        for g in groups:
            existing = next((x for x in target if x.get("matcher") == g.get("matcher")), None)
            label = f"{event}[{g.get('matcher', '*')}]"
            if existing is None:
                target.append(copy.deepcopy(g))
                report += [f"added    {label}: {h['command']}" for h in g["hooks"]]
                continue
            for h in g["hooks"]:
                if any(e.get("command") == h["command"] for e in existing.setdefault("hooks", [])):
                    report.append(f"present  {label}: {h['command']}")
                else:
                    existing["hooks"].append(copy.deepcopy(h))
                    report.append(f"added    {label}: {h['command']}")
    if not hooks:
        settings.pop("hooks", None)
    if src.get("statusLine"):
        cur = settings.get("statusLine")
        if not cur:
            settings["statusLine"] = copy.deepcopy(src["statusLine"])
            report.append(f"added    statusLine: {src['statusLine']['command']}")
        elif cur.get("command") == src["statusLine"]["command"]:
            report.append(f"present  statusLine: {cur['command']}")
        else:
            report.append(f"kept     statusLine already set to '{cur.get('command')}' (not overwritten; usage tracking needs ms-statusline)")
    perms = settings.setdefault("permissions", {})
    for kind in ("allow", "ask"):
        rules = perms.setdefault(kind, [])
        if kind == "allow":
            for old in LEGACY_ALLOW:
                if old in rules:
                    rules.remove(old)
                    report.append(f"removed  permission {old} (too broad; replaced by the narrower rules below)")
        for rule in src.get("permissions", {}).get(kind, []):
            if rule in rules:
                report.append(f"present  {kind} {rule}")
            else:
                rules.append(rule)
                report.append(f"added    {kind} {rule}")
        if not rules:
            del perms[kind]
    return report


def use_plugin_root(settings: dict, src: dict, root: str, command: str | None = None) -> list[str]:
    """Plugin mode: the plugin ships the hooks itself, so drop our copies from settings.json and
    point the status line at the plugin's script (a plugin's bin/ is not on the status line's PATH).
    `command` replaces the plugin path when a launcher outside the versioned folder exists (see global_bin)."""
    report, cmds = [], our_commands(src)
    for event in list(settings.get("hooks", {})):
        for g in settings["hooks"][event]:
            report += [f"removed  {event}: {h['command']} (the plugin provides it)" for h in g.get("hooks", []) if h.get("command") in cmds]
            g["hooks"] = [h for h in g.get("hooks", []) if h.get("command") not in cmds]
        settings["hooks"][event] = [g for g in settings["hooks"][event] if g.get("hooks")]
        if not settings["hooks"][event]:
            del settings["hooks"][event]
    if not settings.get("hooks"):
        settings.pop("hooks", None)
    src["hooks"], src["statusLine"] = {}, None  # merge() then only adds the permissions
    line = {"type": "command", "command": command or f'"{root}/bin/ms-statusline"'}
    cur = (settings.get("statusLine") or {}).get("command", "")
    if cur == line["command"]:
        report.append(f"present  statusLine: {cur}")
    elif not cur or cur.strip('"').endswith("ms-statusline"):
        settings["statusLine"] = line
        report.append(f"{'updated' if cur else 'added  '}  statusLine: {line['command']}")
    else:
        report.append(f"kept     statusLine already set to '{cur}' (not overwritten; usage tracking needs ms-statusline)")
    return report


def remove(settings: dict, src: dict) -> list[str]:
    report, cmds = [], our_commands(src)
    for event in list(settings.get("hooks", {})):
        groups = settings["hooks"][event]
        for g in groups:
            kept = [h for h in g.get("hooks", []) if h.get("command") not in cmds]
            report += [f"removed  {event}: {h['command']}" for h in g.get("hooks", []) if h.get("command") in cmds]
            g["hooks"] = kept
        settings["hooks"][event] = [g for g in groups if g.get("hooks")]
        if not settings["hooks"][event]:
            del settings["hooks"][event]
    if not settings.get("hooks"):
        settings.pop("hooks", None)
    if src.get("statusLine") and (settings.get("statusLine") or {}).get("command", "").strip('"').endswith(src["statusLine"]["command"]):
        del settings["statusLine"]
        report.append("removed  statusLine")
    perms = settings.get("permissions", {})
    for kind in ("allow", "ask"):
        rules = perms.get(kind, [])
        for rule in src.get("permissions", {}).get(kind, []) + (LEGACY_ALLOW if kind == "allow" else []):
            if rule in rules:
                rules.remove(rule)
                report.append(f"removed  {kind} {rule}")
        if kind in perms and not perms[kind]:
            del perms[kind]
    if "permissions" in settings and not settings["permissions"]:
        del settings["permissions"]
    return report


MD_BEGIN = "<!-- dynamia:begin (managed by /dynamia:setup; edit outside this block) -->"
MD_END = "<!-- dynamia:end -->"
MD_FILE = "DYNAMIA.md"
BIN_NAMES = ("ms-workspace", "ms-statusline")


def claude_home() -> Path:
    return settings_path().parent


def bin_dir() -> Path:
    return Path(os.environ.get("BIN_DIR") or Path(os.environ.get("HOME", "~")).expanduser() / ".local" / "bin")


def _backup(path: Path, report: list[str]) -> None:
    backup = path.with_name(f"{path.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(path, backup)
    report.append(f"backup   {backup}")


def global_md(root: Path, dry: bool, undo: bool) -> list[str]:
    """Copy the repo's global instructions to ~/.claude/DYNAMIA.md and import them from ~/.claude/CLAUDE.md with one
    @DYNAMIA.md line inside a marked block; the rest of CLAUDE.md is yours. The copy keeps the import path stable across plugin updates."""
    home = claude_home()
    target, doc, report = home / "CLAUDE.md", home / MD_FILE, []
    block = f"{MD_BEGIN}\n@{MD_FILE}\n{MD_END}"
    source = (root / "CLAUDE.md").read_text()
    linked = target.is_symlink()  # install.sh linked it to the repo file: never write through it
    text = target.read_text() if target.exists() else ""
    a, b = text.find(MD_BEGIN), text.find(MD_END)
    if (a == -1) != (b == -1) or b < a:
        die(f"{target} has a dynamia block start without an end marker (or the reverse); fix it by hand")
    if linked and text == source:
        text, a, b = "", -1, -1  # a copy of our own file: the block replaces it
    if undo:
        if doc.exists():
            report.append(f"removed  {doc}")
            if not dry:
                doc.unlink()
        if a == -1:
            return report + ["present  no dynamia block in CLAUDE.md (nothing to remove)"]
        new = (text[:a] + text[b + len(MD_END):].lstrip("\n")).rstrip() + "\n"
        report.append("removed  dynamia block from CLAUDE.md")
    else:
        if doc.exists() and doc.read_text() == source:
            report.append(f"present  {doc}")
        else:
            report.append(f"{'updated' if doc.exists() else 'added  '}  {doc}")
            if not dry:
                doc.parent.mkdir(parents=True, exist_ok=True)
                doc.write_text(source)
        if a != -1:
            if text[a:b + len(MD_END)] == block:
                return report + ["present  dynamia import in CLAUDE.md"]
            new = text[:a] + block + text[b + len(MD_END):]
            report.append("updated  dynamia block in CLAUDE.md (now an import)")
        else:
            new = text + ("" if not text or text.endswith("\n") else "\n") + ("\n" if text else "") + block + "\n"
            report.append("added    dynamia import in CLAUDE.md" + (" (your content kept above it)" if text else ""))
    if not dry:
        if target.exists() or linked:
            if linked:
                target.unlink()
            else:
                _backup(target, report)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(new)
    return report


LAUNCHER_MARK = "# dynamia launcher"
LAUNCHER = """#!/bin/sh
# dynamia launcher (managed by /dynamia:setup): runs the newest installed dynamia plugin, so an update needs no new setup.
dir="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/plugins/cache"
best=$(for d in "$dir"/*/dynamia/*/; do [ -x "${d}bin/%(name)s" ] || continue; v=${d%%/}; echo "${v##*/} $d"; done 2>/dev/null \
  | sort -t. -k1,1n -k2,2n -k3,3n | tail -1 | cut -d' ' -f2-)
[ -n "$best" ] || { echo "dynamia plugin not found under $dir (install it: /plugin install dynamia@dynamia-tools)" >&2; exit 127; }
exec "${best}bin/%(name)s" "$@"
"""


def is_cached(root: Path) -> bool:
    """True for a plugin installed by Claude Code (.../plugins/cache/<marketplace>/dynamia/<version>): its path holds the version."""
    parts = root.resolve().parts
    return len(parts) >= 5 and parts[-4] == "cache" and parts[-5] == "plugins" and parts[-2] == "dynamia"


def _is_launcher(path: Path) -> bool:
    try:
        return path.is_file() and not path.is_symlink() and LAUNCHER_MARK in path.read_text()[:200]
    except (OSError, UnicodeDecodeError):
        return False


def global_bin(root: Path, dry: bool, undo: bool) -> list[str]:
    """Put ms-workspace and ms-statusline in ~/.local/bin. A cached plugin gets a small launcher that finds the newest version
    (so updates need no new setup); a repo checkout or --plugin-dir gets a link. Only our own links and launchers are replaced."""
    report, dest = [], bin_dir()
    launcher = is_cached(root)
    for name in BIN_NAMES:
        src, dst = root / "bin" / name, dest / name
        old_link = dst.is_symlink() and os.readlink(dst).endswith(f"/bin/{name}")
        ours = old_link or _is_launcher(dst)
        text = LAUNCHER % {"name": name}
        if undo:
            if ours:
                report.append(f"removed  {dst}")
                if not dry:
                    dst.unlink()
        elif launcher and _is_launcher(dst) and dst.read_text() == text:
            report.append(f"present  launcher {dst}")
        elif not launcher and dst.is_symlink() and os.readlink(dst) == str(src):
            report.append(f"present  link {dst}")
        elif ours or not dst.exists() and not dst.is_symlink():
            what = f"launcher {dst} (runs the newest installed plugin)" if launcher else f"link {dst} -> {src}"
            report.append(f"{'updated' if ours else 'added  '}  {what}")
            if not dry:
                dest.mkdir(parents=True, exist_ok=True)
                if ours:
                    dst.unlink()
                if launcher:
                    dst.write_text(text)
                    dst.chmod(0o755)
                else:
                    dst.symlink_to(src)
        else:
            report.append(f"kept     {dst} already exists and is not ours")
    if not undo and str(dest) not in os.environ.get("PATH", "").split(":"):
        report.append(f"note     {dest} is not in PATH; add it to your shell profile")
    return report


def cmd_setup_hooks(args: list[str]) -> int:
    dry = "--dry-run" in args
    undo = "--remove" in args
    project = "--project" in args
    source = SOURCE
    if "--source" in args:
        i = args.index("--source")
        if i + 1 >= len(args):
            die("--source needs a file")
        source = Path(args[i + 1])
    try:
        src = json.loads(source.read_text())
    except (OSError, ValueError) as e:
        die(f"cannot read {source}: {e}")
    target = settings_path(project)
    settings = {}
    if target.exists():
        try:
            settings = json.loads(target.read_text())
        except ValueError as e:
            die(f"{target} is not valid JSON ({e}); fix it first, nothing was changed")
    before = json.dumps(settings, sort_keys=True)
    report = []
    if "--plugin-root" in args and not undo:
        i = args.index("--plugin-root")
        if i + 1 >= len(args):
            die("--plugin-root needs the plugin folder")
        root = args[i + 1].rstrip("/")
        launcher = "--global" in args and is_cached(Path(root))  # the launcher is only installed with --global
        report = use_plugin_root(settings, src, root, f'"{bin_dir() / "ms-statusline"}"' if launcher else None)
    report += remove(settings, src) if undo else merge(settings, src)
    changed = json.dumps(settings, sort_keys=True) != before
    print(f"{'(dry run) ' if dry else ''}{'Removing from' if undo else 'Merging into'} {target}")
    for line in report or ["nothing to do"]:
        print("  " + line)
    if "--global" in args:
        if project:
            die("--global works on your user-level files; drop --project")
        root = Path(args[args.index("--plugin-root") + 1]) if "--plugin-root" in args else SOURCE.parents[1]
        print(f"{'(dry run) ' if dry else ''}{'Removing' if undo else 'Setting up'} global files in {claude_home()} and {bin_dir()}")
        for line in global_md(root, dry, undo) + global_bin(root, dry, undo):
            print("  " + line)
    if not undo and "--plugin-root" not in args and shutil.which("ms-workspace") is None:
        print("  warning: ms-workspace is not in PATH, so the hooks would fail; run ./install.sh first")
    if changed and not dry:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            backup = target.with_name(f"{target.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}")
            shutil.copy2(target, backup)
            print(f"  backup: {backup}")
        target.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n")
        print("Done. Start a new Claude Code session to load the changes.")
    elif not changed:
        print("Already up to date." if not undo else "Nothing to remove.")
    return 0


def setup_problem() -> str | None:
    """One line saying what is missing or broken in the user-level install, or None. Reads files only, never raises."""
    try:
        cfg = json.loads(settings_path().read_text()) if settings_path().exists() else {}
        cmd = ((cfg.get("statusLine") or {}).get("command") or "").strip().strip('"')
        if not cmd:
            return "the usage status line is not installed"
        if cmd.endswith("ms-statusline"):  # ours; another status line is the user's choice
            exists = Path(cmd).exists() if "/" in cmd else shutil.which(cmd) is not None
            if not exists:
                return f"the status line points to a missing file ({cmd})"
        for name in BIN_NAMES:
            link = bin_dir() / name
            if link.is_symlink() and not link.exists():
                return f"{link} is a broken link"
    except Exception:
        return None
    return None


def cmd_setupcheck() -> int:
    """SessionStart hook: tell the user, once per session, when /dynamia:setup is needed. Silent otherwise."""
    if os.environ.get("MS_NO_SETUP_NUDGE"):
        return 0
    problem = setup_problem()
    if problem:
        print(json.dumps({"systemMessage": f"dynamia: {problem}. Run /dynamia:setup, then restart Claude Code."}))
    return 0
