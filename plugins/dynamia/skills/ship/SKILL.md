---
name: ship
description: Publishes a validated batch, or the plain local branch of a repo, to each repo's base branch (direct push or PR, per workspace.toml) after syncing with the remote, re-running the incremental tests and the end-to-end command. Use when the user explicitly asks to ship, publish or push a batch, or to open a pull request (PR) for it; "open a PR" means ship with --pr. Never on your own initiative.
argument-hint: "<batch-name>|--branch [repo] [--pr|--direct]"
allowed-tools: Bash(ms-workspace usage:*) Bash(ms-workspace plan:*)
---

# dynamia:ship

The only step that touches remotes. It never targets release branches and never force-pushes.

It ships two things: a **batch** (`int/<batch>` worktrees) or a **plain branch** (`--branch`: the task branch checked out in a repo's own checkout, which `/dynamia:batch` offers for small single-repo tasks). Everything below applies to both; for a plain branch replace `<batch>` with `--branch [<repo>]` in every command (the repo defaults to the one you are in; it must be on a task branch, not the base branch, with a clean tree). Ship merges a moved base into that branch in the checkout, and leaves the branch there afterwards.

It works from the workspace root or from inside the batch worktree. In a batch worktree the guard blocks `git push`, `gh pr create` and `ship --skip-gate` typed by hand, so always go through `ms-workspace ship`.

**What the user's words mean**
- "open a PR", "abre un PR", "crea el pull request" -> `--pr`: every repo gets `int/<batch>` pushed and a PR to its base branch, whatever its `push` setting.
- "ship", "publish", "push it", "sube esto" -> no `--pr`: each repo uses its configured `push` mode (`direct` pushes to the base branch, `pr` opens a PR).
- If a repo has `push = "ask"`, always ask (PR or direct push) before step 2 and pass the answer as `--pr` or `--direct`; `plan` and `ship` refuse to run without one.
- If it is unclear whether they want a PR or a direct push, ask before step 2: a direct push cannot be undone with a close button.
- An explicit request for a PR is enough: go straight to the plan with `--pr`, without asking whether they would rather push directly.
- "We are done for today" or any plain request to publish is **not** a request for a PR: use the configured mode.

## Steps

0. **Check plan usage first**: `ms-workspace usage --check --need 5`. Exit 0 or 3 (no data): continue. Exit 1 or 2: show the printed numbers and use `AskUserQuestion` (continue / do a smaller step / stop) before doing anything else. If the user stops mid-batch, leave a handoff first: `ms-workspace memory add --type handoff --batch <batch> "state, next step, files touched"`. Never start something that cannot be finished in the remaining window.
1. **Pick the target**: `$ARGUMENTS`, or list batches with `ms-workspace clean`. If the user worked on a plain branch (no batch exists for it), use `--branch`.

2. **Show the plan**: `ms-workspace plan <batch> [--pr]`. For every repo it lists the target branch, push mode, the commit subjects that would be sent and a diffstat. It refuses while agent branches are not integrated: run `/dynamia:integrate` first.

   Then write the plan for the user in a few lines of plain text: per repo, the target branch, push or PR, and the commit subjects. If the plan prints `RECOMMEND A PR`, add one line saying so. Do not ask anything about it: the mode is the configured one unless the user already said `--pr`/`--direct`.

3. **Ship, with one confirmation.** Run `ms-workspace ship <batch> --yes [--pr]` right after the plan text. Claude Code's permission prompt for this command (`ship` is in `ask` on purpose) is the single "are you sure?": do not add an `AskUserQuestion`, do not offer `--skip-e2e` or other variants, and do not try to avoid the prompt. Add `--skip-e2e` only if the user asked for it in this conversation. Never pass `--skip-gate`: the guard blocks it.
   - For a PR, write a descriptive title (imperative, under 70 characters, saying what the change does, not the batch name) and a short description (what and why, notable decisions, how it was verified) from the commits and diff you saw in the plan. Save the description to a file in the scratchpad and pass `--title "<title>" --body-file <file>`. These apply to every repo in the batch; with several repos, keep the text about the batch as a whole. Without them ship builds a basic title and body from the commits.
   - Base moved: it merges `origin/<base>` into the batch and re-runs the tests; this is expected.
   - Conflict, failed t1/e2e, or a rejected push: nothing further is pushed. Report the exact error and stop; do not retry blindly.

4. **After success**: report the pushed repos in one line each, with the t1/e2e result taken from the ship output and anything skipped. Do not run `clean` (it has its own permission prompt): after a direct push say in one line that `ms-workspace clean <batch>` removes the batch; after a PR, that it works once the PR is merged. A plain branch has nothing to clean: tell the user it can be deleted once merged.

## Cleaning later
`ms-workspace clean <batch>` first fetches the base branch from origin and removes the batch without any question only when its work is already there (plain, rebase or squash merge). If the PR is not merged yet it refuses and removes nothing. When the user asks for it, run it and, if it refuses, relay the one-line reason. Discard an unmerged batch only when the user says so (`--force`).

## Notes
- Promotion from the base branch to QA/production is a separate, human decision outside this skill.
- Everything is logged: `ms-workspace log --action ship`.
