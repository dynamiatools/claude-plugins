---
name: tmux-session
description: Lists the project folders under the base directory (default ~/IdeaProjects), lets the user pick one, and starts a detached tmux session running Claude Code inside it with Remote Control enabled. Use when the user asks to open/launch a Claude session in tmux for an existing project, with no cloning involved.
---

# dynamia:tmux-session

Starts a `tmux` session with Claude Code inside a project folder, picking the
folder interactively (the script's own `select` menu does not work when
invoked by Claude, so this skill replaces it with `AskUserQuestion`).

## Steps

1. **List the project folders** (direct children only). The base directory is
   `$CLAUDE_TMUX_BASE_DIR`, defaulting to `~/IdeaProjects`:
   ```bash
   find "${CLAUDE_TMUX_BASE_DIR:-$HOME/IdeaProjects}" -mindepth 1 -maxdepth 1 -type d -exec basename {} \; | sort
   ```
   If there are none, tell the user and stop.

2. **Ask which one to use** with `AskUserQuestion`, offering the folders as
   options. Skip the question if the user already named a folder that matches.

3. **Launch the bundled script detached** (never attached: it would block the
   skill). The script lives next to this file, so use the "Base directory for this
   skill" shown above, not a fixed path (plugin skills are not under `~/.claude/skills`):
   ```bash
   bash "<base directory of this skill>/scripts/claude-tmux.sh" "<chosen-folder>" --detached
   ```
   It creates a single-window tmux session named after the folder, marks the
   folder as trusted, starts Claude Code, and enables Remote Control in the
   background (so the session shows up in claude.ai/code).

   If it fails because the session already exists, report the error as-is and
   ask how to proceed (e.g. attach to the existing one).

4. **Report** the session name and that it can be controlled from the Claude
   app (Remote Control) or attached with `tmux attach -t <session>`.

## See the sessions and ask how they are doing
Read-only, so it never disturbs what a session is doing:
- `ms-workspace tmux ls` lists every tmux session with a guessed state: `working`, `idle`, `needs-you` (a permission prompt waits), `exited` or `unknown`. The state comes from the screen text, so treat it as a hint.
- `ms-workspace tmux status <session> [--lines N]` shows the last lines of what a session shows (secrets on the screen are masked).
- `ms-workspace thanos sessions` does the same for the missions started with `/dynamia:thanos --background`, with the mission summary (steps, tasks, Opus reviews).
- `ms-workspace tmux send <session> <text>` types a line into a session, only when it is `idle` (`--force` overrides). Use it only when the user asks; to follow a mission read its state instead of asking it.

## Notes

- Requires `tmux`, `claude` and `jq` in PATH.
- To end a session you started, use `tmux kill-session -t <session>` (`ms-workspace ps kill` refuses tmux, and `clean` tells you the same).
- If the session does not appear in claude.ai/code, retry manually:
  `tmux send-keys -t <session> "/remote-control" Enter`, then after ~2s
  `tmux send-keys -t <session> Enter`.
