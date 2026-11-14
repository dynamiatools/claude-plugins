---
name: thanos
description: Runs a complex goal from start to finish with minimal interruptions, inside its own batch worktree, with a branch per task, a step cap, a strict guard and at most three Opus reviews. Use only when the user explicitly asks for THANOS, an autonomous mission, or to "do it all yourself".
argument-hint: "<goal> [--max-steps N]"
allowed-tools: Bash(ms-workspace thanos:*) Bash(ms-workspace usage:*) Bash(ms-workspace batch new:*) Bash(ms-workspace status:*) Bash(ms-workspace test:*) Bash(ms-workspace integrate:*)
---

# dynamia:thanos

> **Fine. I'll do it myself.**
> THANOS activated. Mission accepted.

Print those two lines when you start. The user defines the goal; you get it done. The rules that make it safe are enforced by hooks, not by good will: do not try to get around them.

## What is different from the normal flow
- It always works in a **worktree of its own** (`batch new`), never in the user's checkout. No question about worktree or plain branch.
- **One question round, at the start, and none after.** Afterwards decide with sensible defaults and write each decision under `## Decisions` in `THANOS.md`.
- **No parallel agents.** The only agent you may launch is the Opus reviewer `dynamia:boss`, in the foreground, **at most 3 times**: (1) before the first line is written, (2) at the end of the mission, (3) one rescue when something blows up (a milestone `test t1` that cannot be fixed after two different attempts, or a merge that breaks the batch). Ask it for a report of at most 25 lines. Search with Grep and Glob yourself.
- The strict guard **blocks**, it does not ask: pushes (except the batch branch), `ship`, `merge`, `clean`, deploys, remote hosts, production, destructive git or shell, edits outside the batch. Read-only `gh` lookups (`gh issue view|list`, `gh pr view|list|checks`, `gh run list`) are allowed, so read the issue text instead of guessing it; any `gh` that writes is blocked. A blocked action is not a failure of the mission: record it, park the task, go on.
- It never ships and never opens a PR. Integrating and publishing stay with the user.

## Steps

0. **Check plan usage**: `ms-workspace usage --check --need 20`. Exit 1 or 2: show the numbers and use `AskUserQuestion` (continue / smaller mission / stop). Also tell the user once if their sign-in is about to expire when you know it.
1. **Brief, one `AskUserQuestion` round** (skip what the request already answers): the goal in one sentence, the success criteria (each checkable with a command or a file), which repos, and the step cap. Do not ask anything else, then or later.
2. **Open the batch**: `ms-workspace batch new thanos-<slug> <repos...>` (kebab-case slug from the goal). Work only inside `working-trees/thanos-<slug>/<repo>`.
3. **Plan.** Write the success criteria and the task list in `<batch>/THANOS.md` (it already has the sections): `- [ ] [S|M|L] name: what`, short names, in dependency order, each task small enough to finish and test in one go (S about 2 steps, M 4, L 8; split anything bigger). Then `ms-workspace thanos estimate <batch>`.
4. **Opus review 1/3**: launch `dynamia:boss` with the goal, criteria, task list and the files the plan touches; ask whether the plan is complete, safe and in the right order, in at most 25 lines. Fix the plan with what it finds; record the verdict under Decisions.
5. **Start the mission**: `ms-workspace thanos start <batch> --goal "<goal>" --opus-used 1 [--max-steps N | --until-usage PCT]`. `--opus-used 1` records the review of step 4, which happened before the mission existed, so the counter and the cap of three stay true. When the user says to go on "until usage reaches X%", use `--until-usage X`: the percentage (5h or weekly, whichever is higher) is then the limit and the step cap only guards against a runaway loop. The default cap is 30 steps (the config key `[thanos] max_steps`); when the estimate is above the cap the command warns, so tell the user in one line and raise the cap only if they asked for it. From here the purple badge `[THANOS IS WORKING]` shows in the status line and the Stop hook keeps you going while tasks are open.
6. **Loop, one task at a time:**
   1. `ms-workspace thanos task start <name>` (creates `agent/<batch>/<name>` from the batch branch).
   2. Implement it; read the code the change touches first. Commit locally in small steps.
   3. `ms-workspace test t0`; fix failures. If an approach fails, write it under `## Failed attempts` and never repeat it.
   4. `ms-workspace thanos task done <name>` (merges it `--no-ff` into the batch branch, ticks the line in `THANOS.md`, and pushes the batch branch to origin every few tasks as a backup).
   5. After a milestone (a group of related tasks) run `ms-workspace test t1 <batch>`.
   - Blocked by a guard or a missing permission: `ms-workspace thanos block --task <name> "<what and why>"` (it records the blocker and parks the task `[!]` in the ledger), then go to the next. Never retry the same command in a disguised form.
   - Waiting for the Opus reviewer (it runs in the background of the harness): run `ms-workspace thanos wait [MINUTES]` first and then end your turn. While the window is open the Stop hook lets you stop without counting steps; the reviewer's notification wakes you up. Do not poll.
   - A conflict on `task done` leaves you on the task branch: rebase it on the batch branch, fix, run `task done` again.
7. **Finish**: when no `[ ]` task is left, run `ms-workspace test t1 <batch>`, check every success criterion with evidence (the command and its result), then **Opus review 2/3** over the whole batch against the original goal. Fix what is real, then `ms-workspace thanos done`.
8. **Report** in the user's language, short: the goal and whether each criterion passed (with the command), the commits and files changed (`git diff --stat` against the base), the steps and Opus reviews used, the parked tasks and blockers, and what is left. Say what was not verified. Tell them the next step is theirs: `ms-workspace plan <batch>` and `/dynamia:ship`.

## When the mission pauses
It pauses by itself at the step cap, at critical plan usage, or after three steps without progress, and writes a handoff. Say so in one line with the reason. To continue: `ms-workspace thanos resume <batch>` (raise the cap first with a new `thanos start` only if the user wants more steps). `ms-workspace thanos stop` cancels the mission and keeps the batch.

## Notes
- Status at any time: `ms-workspace thanos status`. The ledger `THANOS.md` is the memory that survives compaction: keep Decisions, Failed attempts and Blockers current.
- Configure it in `workspace.toml`: `[thanos] max_steps`, `max_opus`, `push_every` (0 turns the backup push off) and `deny_hosts = ["prod.example.com"]` (a command that names one of them is blocked).
- Commands that are not on the known-safe list still go through the user's normal permissions, so allowlist the build and test commands of the repo to run unattended.
