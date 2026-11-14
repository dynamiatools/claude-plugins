#!/usr/bin/env bash
# claude-tmux: start a tmux session running Claude Code in a subfolder of a base directory.
# The session has a single window, and its name is the subfolder name.
#
# Usage:
#   claude-tmux.sh <subfolder>              # create the session and attach
#   claude-tmux.sh <subfolder> --detached   # create the session in the background
#
# Environment:
#   CLAUDE_TMUX_BASE_DIR   base directory holding the projects (default: $HOME/IdeaProjects)
set -euo pipefail

BASE_DIR="${CLAUDE_TMUX_BASE_DIR:-$HOME/IdeaProjects}"

DETACHED=0
CHOSEN=""
for arg in "$@"; do
    case "$arg" in
        --detached) DETACHED=1 ;;
        *) CHOSEN="$arg" ;;
    esac
done

for bin in tmux claude jq; do
    command -v "$bin" >/dev/null 2>&1 || { echo "Error: $bin is not installed or not in PATH." >&2; exit 1; }
done

if [ -z "$CHOSEN" ]; then
    echo "Usage: $(basename "$0") <subfolder> [--detached]" >&2
    exit 1
fi

case "$CHOSEN" in
    */*|.*|-*|"") echo "Error: '$CHOSEN' is not a plain folder name." >&2; exit 1 ;;
esac

if [ ! -d "$BASE_DIR/$CHOSEN" ]; then
    echo "Error: '$CHOSEN' does not exist inside $BASE_DIR." >&2
    exit 1
fi

SUB_DIR="$BASE_DIR/$CHOSEN"
# tmux targets cannot contain '.' or ':'; keep the session name to safe characters.
SESSION_NAME="$(printf '%s' "$CHOSEN" | tr -c 'A-Za-z0-9_-' '-')"
CLAUDE_CONFIG="$HOME/.claude.json"

if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
    echo "Error: a tmux session named '$SESSION_NAME' already exists." >&2
    exit 1
fi

# Mark the directory as trusted so Claude skips the "trust this folder" dialog.
if [ -f "$CLAUDE_CONFIG" ]; then
    # Write next to the real file and rename, so a concurrent writer never sees a truncated file
    # and a symlinked ~/.claude.json keeps pointing at its target.
    real="$(readlink -f "$CLAUDE_CONFIG" 2>/dev/null || echo "$CLAUDE_CONFIG")"
    tmp="$real.ms-$$.tmp"
    if jq --arg dir "$SUB_DIR" \
        '.projects[$dir] = ((.projects[$dir] // {}) + {"hasTrustDialogAccepted": true})' \
        "$real" > "$tmp"; then
        chmod --reference="$real" "$tmp" 2>/dev/null || true
        mv "$tmp" "$real"
    else
        rm -f "$tmp"
    fi
fi

# The tmux server keeps the working directory it was started from; start it in the project folder, never in a
# batch worktree, or `ms-workspace clean` later sees the server as a process running inside that batch.
cd "$SUB_DIR"
printf -v CLAUDE_CMD 'claude --name %q; tmux kill-session -t %q' "$(hostname):$CHOSEN" "$SESSION_NAME"
tmux new-session -d -s "$SESSION_NAME" -n "$SESSION_NAME" -c "$SUB_DIR" "$CLAUDE_CMD"

# Enable Remote Control in the background once Claude shows its prompt, so the
# session appears in claude.ai/code without manual steps.
(
    for _ in $(seq 1 30); do
        sleep 1
        if tmux capture-pane -t "$SESSION_NAME" -p 2>/dev/null | grep -q '^❯'; then
            break
        fi
    done
    tmux send-keys -t "$SESSION_NAME" "/remote-control" Enter
    sleep 1.5
    tmux send-keys -t "$SESSION_NAME" Enter
) >/dev/null 2>&1 &
disown

if [ "$DETACHED" -eq 1 ]; then
    echo "tmux session '$SESSION_NAME' created in the background."
    echo "Attach with: tmux attach -t $SESSION_NAME"
else
    exec tmux attach-session -t "$SESSION_NAME"
fi
