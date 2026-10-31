# issue-board

A small side pane with the GitHub issues the agent is working on, kept across sessions so a session that died can be resumed without starting from zero.

It is a mod (a hooks module), not a skill: it changes the interface and adds no skills or agents. It only reads from GitHub and writes nothing there.

## How it works
- It watches the Bash commands the agent runs and picks up issue numbers from them:
  - `gh issue view|comment|edit|develop|reopen N` marks an issue as `WORK`; `gh issue close N` as `DONE`.
  - `gh pr create` with `Closes #N`, `Fixes #N` or `Resolves #N` marks it `PR`.
  - `git switch -c fix/123-title` (or `checkout -b`, `branch`) with a number at the start of the name marks `#123` as `WORK` and remembers the branch.
  - `git commit` with `#N` in the command marks it `WORK`.
- The title comes from `gh issue view N --json title`. Without `gh`, or without access, the pane shows the `#N` alone.
- The pane opens by itself on the first issue. It shows a colored title with the repo, and one entry per issue: badge, number, title and time since the last activity (newest first). Long titles wrap under themselves, up to three rows.
- The list is stored per repository (`$.store`, kept between sessions). When a new session starts in the same repo, the issues still open are added to the system prompt, so the agent offers to continue them and checks each one on GitHub first.
- `/issues` shows the list and opens the pane; `/issues clear` empties it.

## Works with `dynamia`, but does not need it
The plugin keeps and resumes its own state. If the `dynamia` plugin is installed (its skills are listed as `/dynamia:<skill>`), the resume note suggests `/dynamia:memory` for a longer handoff; otherwise suggest `/plugin install dynamia@dynamia-tools`. Nothing breaks without it.

## Install
```
/plugin install issue-board@dynamia-tools
```

## Limits
- Detection is by the shell command text: an issue worked on without any of the commands above does not appear.
- The repository is taken from `git remote get-url origin`; only GitHub remotes are tracked.
- The pane needs a wide terminal; below that it waits undrawn.

## Tests
```
claude plugin test plugins/issue-board
```
