---
name: ship
description: Publishes a validated batch, or the plain local branch of a repo, to each repo's base branch (direct push or PR, per workspace.toml) after syncing with the remote, re-running the incremental tests and the end-to-end command. Use when the user explicitly asks to ship, publish or push a batch, or to open a pull request (PR) for it; "open a PR" means ship with --pr. Never on your own initiative.
argument-hint: "<batch-name>|--branch [repo] [--pr|--direct]"
allowed-tools: Bash(ms-workspace usage:*) Bash(ms-workspace plan:*)
---

# dynamia:ship

The only step that touches remotes. It never targets release branches and never force-pushes.

It ships two things: a **batch** (the batch's worktrees and their `<type>/<batch>` branch) or a **plain branch** (`--branch`: the task branch checked out in a repo's own checkout, which `/dynamia:batch` offers for small single-repo tasks). Everything below applies to both; for a plain branch replace `<batch>` with `--branch [<repo>]` in every command (the repo defaults to the one you are in; it must be on a task branch, not the base branch, with a clean tree). Ship merges a moved base into that branch in the checkout, and leaves the branch there afterwards.

It works from the workspace root or from inside the batch worktree. In a batch worktree the guard blocks pushes to the base branch, force pushes, `gh pr create` and `ship --skip-gate` typed by hand, so always go through `ms-workspace ship` to publish. (Pushing the batch's own branch for backup, `git push -u origin <branch>`, is allowed with a confirmation; it is not a ship.)

**What the user's words mean**
- "open a PR", "abre un PR", "crea el pull request" -> `--pr`: every repo gets the batch branch pushed and a PR to its base branch, whatever its `push` setting.
- "ship", "publish", "push it", "sube esto" -> no `--pr`: each repo uses its configured `push` mode (`direct` pushes to the base branch, `pr` opens a PR).
- If a repo has `push = "ask"`, always ask (PR or direct push) before step 2 and pass the answer as `--pr` or `--direct`; `plan` and `ship` refuse to run without one.
- If it is unclear, do not ask: use the configured mode. The ship permission prompt is the only confirmation.
- An explicit request for a PR is enough: go straight to the plan with `--pr`, without asking whether they would rather push directly.
- "We are done for today" or any plain request to publish is **not** a request for a PR: use the configured mode.

## Steps

0. **Check plan usage first**: `ms-workspace usage --check --need 5`. Exit 0 or 3 (no data): continue. Exit 1 or 2: show the printed numbers in one line and continue; the ship prompt in step 3 is the only confirmation. Do not use `AskUserQuestion`. If the user stops mid-batch, leave a handoff first: `ms-workspace memory add --type handoff --batch <batch> "state, next step, files touched"`. Never start something that cannot be finished in the remaining window.
1. **Pick the target**: `$ARGUMENTS`, or list batches with `ms-workspace clean`. If the user worked on a plain branch (no batch exists for it), use `--branch`.

2. **Show the plan**: `ms-workspace plan <batch> [--pr]`. For every repo it lists the target branch, push mode, the commit subjects that would be sent and a diffstat. It refuses while agent branches are not integrated: run `/dynamia:integrate` first.

   Then write the plan for the user in a few lines of plain text: per repo, the target branch, push or PR, and the commit subjects. If the plan prints `RECOMMEND A PR`, add one line saying so and, once, that `[ship] recommended_action = "pr"` in `workspace.toml` makes big changes open a PR automatically (then the plan says `PR chosen automatically` and there is nothing to ask). Do not ask anything else about it: the mode is the configured one unless the user already said `--pr`/`--direct`.

3. **Ship, with one confirmation.** Run `ms-workspace ship <batch> --yes [--pr]` right after the plan text. A push straight to the base branch makes Claude Code ask once (the guard hook asks; a PR-only ship, `--pr` or `push = "pr"`, goes through without a prompt, since a PR is reversible). That prompt, when it appears, is the single "are you sure?": do not add an `AskUserQuestion`, do not offer `--skip-e2e` or other variants, and do not try to avoid it. Without an `[e2e]` command ship skips end-to-end by itself. Add `--skip-e2e` only if the user asked for it in this conversation. Never pass `--skip-gate`: the guard blocks it.
   - For a PR, write a descriptive title (imperative, under 70 characters, saying what the change does, not the batch name) and a short description (what and why, notable decisions, how it was verified) from the commits and diff you saw in the plan. Save the description to a file in the scratchpad and pass `--title "<title>" --body-file <file>`. These apply to every repo in the batch; with several repos, keep the text about the batch as a whole. Without them ship builds a basic title and body from the commits.
   - Base moved: it merges `origin/<base>` into the batch and re-runs the tests; this is expected.
   - Conflict, failed t1/e2e, or a rejected push: nothing further is pushed. Report the exact error and stop; do not retry blindly.

4. **After success**: report the pushed repos in one line each (for a PR, the link ship prints: `pushed <repo>: PR <url>`, also kept in `ms-workspace log --action ship`), with the t1/e2e result taken from the ship output and anything skipped. If the user then asks to merge it, use `/dynamia:merge`; never `gh pr merge` by hand. Do not run `clean` yourself unless the user asks: after a direct push say in one line that `ms-workspace clean <batch>` removes the batch; after a PR, that it works once the PR is merged. A plain branch has nothing to clean: tell the user it can be deleted once merged.

## Cleaning later
`ms-workspace clean <batch>` first fetches the base branch from origin and removes the batch without any question only when its work is already there (plain, rebase or squash merge). If the PR is not merged yet it refuses and removes nothing. When the user asks for it, run it and, if it refuses, relay the one-line reason. Discard an unmerged batch only when the user says so (`--force`).

## Notes
- Promotion from the base branch to QA/production is not done here. If the user asks for it, use `/dynamia:promote` (a PR from the base to the release branch).
- Everything is logged: `ms-workspace log --action ship`.
