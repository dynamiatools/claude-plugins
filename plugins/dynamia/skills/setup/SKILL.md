---
name: setup
description: Finishes the dynamia install, the part a plugin cannot do itself - status line and permissions in settings.json, the global instructions in ~/.claude/DYNAMIA.md, and the ms-workspace and ms-statusline launchers in ~/.local/bin - merging without overwriting your entries. Use right after installing or updating the plugin, or when any of those is missing.
argument-hint: "[--project] [--remove]"
disable-model-invocation: true
allowed-tools: Bash(ms-workspace doctor:*), Bash(ms-workspace --help:*)
---

# dynamia:setup

A plugin ships skills, agents, hooks and `bin/`, but it cannot set `statusLine` or `permissions`, load a global `CLAUDE.md` or put tools in your shell PATH. This skill does that part: it merges `settings/hooks.example.json` into a settings file and, with `--global`, copies the plugin's `CLAUDE.md` to `~/.claude/DYNAMIA.md` and adds an `@DYNAMIA.md` import line to `~/.claude/CLAUDE.md` between `dynamia:begin/end` markers (the rest of your file stays untouched; a backup is written first; a link to the repo file is replaced, never written through) and puts `ms-workspace` and `ms-statusline` in `~/.local/bin` as small launchers that run the newest installed plugin version (the status line uses them too), so a plugin update needs no new setup. The merge is idempotent, keeps every other hook, permission and setting, keeps a status line that someone else configured, and writes a timestamped backup before changing anything.

Scope: `~/.claude/settings.json` by default, or the current project's `.claude/settings.json` with `--project`.

## Steps

1. **Pick the mode**: if this skill runs from the installed plugin, its folder is `${CLAUDE_PLUGIN_ROOT}`; use it as `--plugin-root "${CLAUDE_PLUGIN_ROOT}"` (the plugin provides the hooks, so they are not copied into settings.json, and an older copy of them is removed). The plugin's `bin/` is on the PATH of the Bash tool, so use `"${CLAUDE_PLUGIN_ROOT}/bin/ms-workspace"` for every command below if `ms-workspace` is not found. Without the plugin (a clone plus `./install.sh`), omit `--plugin-root` and check `ms-workspace --help | head -1`; if that fails, tell the user to run `./install.sh` and stop.

2. **Preview**: `ms-workspace setup-hooks --dry-run --global --plugin-root "${CLAUDE_PLUGIN_ROOT}" $ARGUMENTS` (drop `--global` with `--project`, which only touches the project's settings). Show the report: lines starting with `added` / `updated` are what will change, `present` is already installed, `kept` is something left untouched on purpose (for example another status line).

3. **Confirm** with `AskUserQuestion`: apply to the user-level settings, apply to this project only, or cancel. If the report says `nothing to do` or `Already up to date`, say so and stop.

4. **Apply**: the same command without `--dry-run` (add `--project` if chosen). Report the backup path.

5. **Verify**: `ms-workspace doctor | sed -n '/Hooks:/,/Plan usage:/p'` and remind the user to start a new Claude Code session, because hooks load at session start.

## Notes
- The launchers find the newest version by themselves, so `/plugin update` needs no new setup. Run this skill again only to refresh the `~/.claude/DYNAMIA.md` copy (`ms-workspace doctor` says when it is outdated) or after moving the Claude config folder.
- If `~/.local/bin` is not in PATH the report says so; tell the user to add it to the shell profile.
- To undo: `ms-workspace setup-hooks --remove`; it removes only what this tool added.
- If settings.json is not valid JSON the command stops without touching it; show the error and ask the user to fix the file.
- If another status line is already configured, usage tracking needs it chained to `ms-statusline`; explain this instead of overwriting it.
