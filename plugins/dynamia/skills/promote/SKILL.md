---
name: promote
description: Promotes a repo's base branch to a release branch (qa or main) by opening a pull request, with ms-workspace promote. Use when the user explicitly asks to promote, release, send to production, or pass the base branch to qa or main. Never on your own initiative.
argument-hint: "[repo] [--to qa|main] [--direct]"
allowed-tools: Bash(ms-workspace usage:*) Bash(ms-workspace release:*)
---

# dynamia:promote

`/dynamia:ship` sends work to the base branch and never touches release branches. This skill is the separate, human-triggered step that moves the base branch to `qa` or `main`. It works on origin's refs only: no checkout, branch or worktree changes.

The destination must be listed in the repo's `release = [...]` in `workspace.toml`. The default is a **pull request** from the base branch into the release branch. `--direct` pushes the base to the release branch as a fast-forward (never forced); use it only if the user asks for it in this conversation.

## Steps

1. **Pick repo and destination.** The repo is `$ARGUMENTS`, or the one you are in. If it has more than one release branch and the user did not say which, ask (one short question: qa or main) and pass `--to`. "Production" normally means `main`; if unsure, ask.
2. **Show what goes up**: `ms-workspace release status <repo> --fetch`. Tell the user in a few lines: how many commits wait, the mix by type, any `BREAKING` line and any hotfix drift (commits only on the release branch). If it says up to date, stop there.
3. **Open the PR with one confirmation.** Run `ms-workspace promote <repo> --to <branch> --yes`. Claude Code's permission prompt for this command (`promote` is in `ask` on purpose) is the single "are you sure?": do not add an `AskUserQuestion` and do not try to avoid the prompt. Before it, confirm the repository and target branch in your text, as the global rules require.
   - Without `--title`/`--body-file`, the title is "Promote <base> to <branch>" and the body lists the commits by type with breaking changes first. Pass your own only if the user wants different text.
   - Local commits on the base branch that are not pushed are not promoted; the plan warns about them. Tell the user.
   - If it fails (cannot fetch, `gh` missing, a PR already exists), report the exact error and stop; do not retry blindly.
4. **After success**: give the PR link printed by `gh` in one line. Merging is the user's. There is no undo: a bad promotion is reverted with a PR.

## Notes
- Tests are not re-run here: the commits already passed `/dynamia:ship`, and the PR is where CI and reviewers check the promotion. Say so in the report.
- Everything is logged: `ms-workspace log --action promote`.
