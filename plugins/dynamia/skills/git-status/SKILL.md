---
name: git-status
description: Shows a compact, emoji-based status card for the git repo in the current directory (branch, last commit, working tree, main/master vs remote, pending PR, active issue and a to-do list). Read-only. Use when the user asks for the repo status, where things stand, or what is pending in the current branch. Triggers on "cómo va el repo", "qué está pendiente en esta rama".
---

# dynamia:git-status

Renders a compact status card (emojis, no ASCII borders) for the git repo in
the current working directory. Read-only: it never pushes, commits or creates
PRs.

## Steps

1. **Check the cwd is a git repo**:
   ```bash
   git rev-parse --is-inside-work-tree 2>/dev/null
   ```
   If it fails, say "This directory is not a git repository" and stop.

2. **Branch and last commit**:
   ```bash
   git branch --show-current
   git log -1 --format='%h %s%n%an%n%cr'
   basename "$(git rev-parse --show-toplevel)"
   ```

3. **Working tree**:
   ```bash
   git status --porcelain
   ```
   Summarize in one line (e.g. "3 modified, 1 untracked"). If clean, show
   "clean ✨".

4. **main/master vs remote** (best-effort; never block on network failures):
   ```bash
   git fetch origin --quiet 2>/dev/null
   ```
   Prefer `origin/main`, then `origin/master`. With whichever exists:
   ```bash
   git log -1 --format='%cr' origin/<base>
   git rev-list --left-right --count origin/<base>...HEAD
   ```
   The first gives when the remote last updated; the second gives
   "behind\tahead" for the current branch. Skip the ahead/behind comparison if
   the current branch IS the base branch. If no remote main/master exists,
   omit the line entirely.

5. **Pending PR** (uses `gh`; if unavailable or failing, show
   "— could not query" instead of failing the whole skill):
   ```bash
   gh pr list --head "$(git branch --show-current)" --json number,title,baseRefName,url,statusCheckRollup,reviewDecision --limit 1
   ```
   If an open PR exists, show number, title, target branch and a checks
   summary (✅/❌/🟡 running). Include unresolved review threads only if `gh`
   exposes them simply; never invent data. No PR → "— none".

6. **Related issue**:
   - Use an issue referenced by the PR body ("Closes #N", "Fixes #N").
   - Otherwise infer from the branch name if it follows `feature/123-...`.
   - If found: `gh issue view <N> --json number,title,assignees` and show
     whether it is assigned to the current user.
   - If nothing can be inferred, show "— none". Do not guess.

7. **"Pending" section**, only when applicable:
   - "N unpushed commit(s)" (compare `HEAD` with `@{upstream}` if set).
   - "N unresolved PR comments" (if obtained in step 5).
   - "Failing PR checks" (if any check is ❌).
   If nothing is pending, show "✅ All up to date".

8. **Render the card** exactly in this format, omitting any line whose data
   does not apply or could not be obtained:

   ```
   📍 <repo-name> · branch <current-branch>

   📝 Last commit: <short-hash> <message>
      👤 <author> · 🕑 <relative-date>

   🌳 Working tree: <summary>

   🔄 <main-or-master>: origin updated <relative-date> · your branch is <N> behind / <N> ahead / up to date

   🔀 PR #<N> "<title>" → <target-branch>
      <✅/❌/🟡> <checks-summary> · 💬 <N> unresolved comments
      (or: 🔀 PR: — none)

   🎫 Issue #<N> "<title>" (assigned to you / unassigned)
      (or: 🎫 Issue: — none)

   ⚠️ Pending:
      • ...
      (or: ✅ All up to date)
   ```

## Notes

- Commands run in the cwd as-is; no fixed paths are assumed.
- If `gh` is not authenticated or the remote is not on GitHub, show the PR and
  issue blocks as "— could not query" and keep the rest of the card.
