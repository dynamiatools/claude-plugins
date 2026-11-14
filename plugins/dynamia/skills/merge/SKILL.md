---
name: merge
description: Merges the pull requests that /dynamia:ship opened for a batch once their checks pass, and brings the base branch of the local checkout up to date, with ms-workspace merge. Use when the user explicitly asks to merge the PR, or to merge and sync the base branch. Never on your own initiative.
argument-hint: "<batch> [--method merge|squash|rebase]"
allowed-tools: Bash(ms-workspace usage:*)
---

# dynamia:merge

The step after `/dynamia:ship --pr`: it merges the PR of each repo of the batch and updates the local base branch. Merging is the user's decision: run it only when they ask for it in this conversation. Never call `gh pr merge` yourself: inside a batch worktree a hook blocks it, and this command also waits for CI and syncs the checkout.

## Steps

1. **Pick the batch**: `$ARGUMENTS`, or list batches with `ms-workspace clean`. A plain-branch ship has no batch: merge it with the user's own `gh` or ask them.
2. **Show the plan**: `ms-workspace merge <batch>`. It lists each PR, its state, its checks (pass / pending / failed) and whether it can be merged. Tell the user in a few lines. If a check failed or there is no PR, say so and stop.
3. **Merge with one confirmation**: `ms-workspace merge <batch> --yes [--method merge|squash|rebase] [--wait SECONDS]`. The permission prompt (the guard asks on `merge --yes`) is the single "are you sure?": do not add an `AskUserQuestion`. Without `--method` it uses `[ship] merge_method` from `workspace.toml`, else a merge commit. It waits up to 10 minutes for pending checks, refuses to merge when one failed, then fetches the base branch and fast-forwards the repo's own checkout when it is clean and on that branch.
   - Failed or still-pending checks: report the exact message and stop; do not retry in a loop.
4. **After success**: one line per repo (PR number, method, whether the base was updated or why not). Say that `ms-workspace clean <batch>` removes the batch now (run it only if the user asks; if it refuses because a process runs inside the batch, relay its one-line reason).

## Notes
- Everything is logged: `ms-workspace log --action merge`.
- Promotion from the base branch to QA/production is `/dynamia:promote`, not this.
