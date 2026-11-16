---
name: test
description: Runs the workspace test levels with ms-workspace test, t0 for what changed here, t1 for a whole batch, t2 for end to end. Use when the user asks to test, run the tests or check that a change works.
argument-hint: "t0 | t1 [batch] | t2 [batch]"
---

# dynamia:test

| Level | Command | Tests |
|---|---|---|
| t0 | `ms-workspace test t0` | what changed in the current repo; a pass is remembered by code hash, `--no-cache` forces a run |
| t1 | `ms-workspace test t1 [batch]` | affected plus `critical` modules of every changed repo of the batch |
| t2 | `ms-workspace test t2 [batch]` | the `[e2e]` command |

## Steps
1. Default to `t0` inside a worktree, `t1` when the user names a batch, `t2` only when asked.
2. Show the PASS/FAIL line. On failure hand the printed output to the `dynamia:test-triage` agent first and fix only what it points to; when JUnit reports exist the tool already prints a summary.
3. A `t1` or `t2` run can take minutes: when there is other work to do, hand it to `dynamia:runner` in the background (give it the exact command and directory) and keep going; it reports the first real error and the log path. For a log that is long, `dynamia:log-triage` reads it instead of you.
4. Say plainly when a result was cached ("same code and command already passed").
5. Repo `env = [...]` variables from `workspace.toml` are applied by the tool; do not export them by hand.
