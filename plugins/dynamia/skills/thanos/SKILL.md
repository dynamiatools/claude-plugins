---
name: thanos
description: Runs a complex goal from start to finish with minimal interruptions, inside its own batch worktree, with a branch per task, a step cap, a strict guard and at most three Opus reviews. Use only when the user explicitly asks for THANOS, an autonomous mission, or to "do it all yourself".
argument-hint: "<goal> [--max-steps N] | --background <goal> | --from-brief <file> | extend <batch> <goal>"
allowed-tools: Bash(ms-workspace thanos:*) Bash(ms-workspace usage:*) Bash(ms-workspace batch new:*) Bash(ms-workspace status:*) Bash(ms-workspace test:*) Bash(ms-workspace integrate:*) Bash(ms-workspace tmux:*)
---

# dynamia:thanos

> **Fine. I'll do it myself.**
> THANOS activated. Mission accepted.

Print those two lines when you start (prefix the second with 🟣). The user defines the goal; you get it done. The rules that make it safe are enforced by hooks, not by good will: do not try to get around them.

## What is different from the normal flow
- It always works in a **worktree of its own** (`thanos new`), never in the user's checkout. No question about worktree or plain branch.
- **It needs no workspace.** Outside a workspace (no `.dynamia/workspace.toml`), `ms-workspace thanos new <slug> [repo-path...]` registers the repo (default: the repo of the current directory) and opens the worktree under `~/.dynamia/thanos/working-trees/thanos-<slug>/<repo>`; the base branch is the repo's default (origin's HEAD, else main, master, next or develop). There is no `test`, `integrate` or `ship` there: run the repo's own test and build commands (from its CLAUDE.md or README) in place of `ms-workspace test`, and note which ones under `## Decisions`. Everything else is the same.
- **One question round, at the start, and none after.** Afterwards decide with sensible defaults and write each decision under `## Decisions` in `THANOS.md`.
- **Agents: the Opus reviewer is rare, the cheap helpers are free to use.** The Opus reviewer `dynamia:boss` runs in the foreground **at most 3 times**: (1) before the first line is written, (2) at the end of the mission, (3) one rescue when something blows up (a milestone `test t1` that cannot be fixed after two different attempts, or a merge that breaks the batch). Ask it for a report of at most 25 lines. The Haiku helpers are not counted as Opus reviews (up to `[thanos] max_cheap` launches, 40 by default) and may run in the background; use them so your own context stays on the code: `dynamia:scout` to locate code, `dynamia:test-triage` for a failing test run, `dynamia:log-triage` for the log of a server or container, `dynamia:summarizer` for diffs and history, `dynamia:runner` to start and watch anything slow (a full `test t1`, a build, a dev server) while you go on with the next task, and `dynamia:pre-review` before the final Opus review. Any other agent type is blocked. Their answer is a lead, not a verdict: open what they point to before you act on it.
- The strict guard **blocks**, it does not ask: pushes (except the batch branch), `ship`, `merge`, `clean`, deploys, remote hosts, production, destructive git or shell, edits outside the batch. Read-only `gh` lookups (`gh issue view|list`, `gh pr view|list|checks`, `gh run list`) are allowed, so read the issue text instead of guessing it; any `gh` that writes is blocked. A blocked action is not a failure of the mission: record it, park the task, go on.
- It is free on its own branches (the batch branch and `agent/<batch>/*`): push, force-push, delete and rename them, locally and on origin, so push a task branch as a backup whenever it helps. Any other branch is blocked.
- Start dev servers and watchers with `ms-workspace thanos run --name web -- pnpm dev`; they are the mission's own and `ms-workspace thanos kill web` (or `kill <pid>`) stops them, and `pause`, `done` and `stop` clean them up. Plain `kill`/`pkill` work only on processes that work inside the batch; never kill one you did not start.
- A side panel with the task list (`/dynamia-thanos-panel`) opens by itself at `thanos start` and follows `THANOS.md`: keep the task lines current.
- It never ships and never opens a PR. Integrating and publishing stay with the user.

## Background mode: `--background <goal>`
Runs the mission in a **new main session of its own in tmux**, so this session stays free. Use it when the user asks for the mission "in the background", "in another session" or "in tmux". You do **not** run the mission here: you prepare it, ask, launch and report.
1. `ms-workspace usage --check --need 20` as in step 0 below.
2. **Always ask first, even when the request is clear**, with one `AskUserQuestion` round: the goal in one sentence, the success criteria (each checkable with a command or a file), which repos, the step cap, and the confirmation that it should start now in a background tmux session. This is the only question round of the whole mission; the launch below refuses to run without it.
3. `ms-workspace thanos new <slug> [repos...]` and write the answers to `<batch>/THANOS-BRIEF.md` (Goal, Success criteria, Repos, Step cap, anything the user said about priorities).
4. `ms-workspace thanos launch <batch> --yes [--max-steps N | --until-usage PCT]`. Claude Code asks the user once more to approve it; that is expected. It starts `thanos-<batch>` in tmux and runs `/dynamia:thanos --from-brief <batch>/THANOS-BRIEF.md` there.
5. Report in two lines: the session name, and how to follow it: `ms-workspace thanos sessions` (state and last screen lines; `needs-you` means a permission prompt waits), `tmux attach -t thanos-<batch>` or claude.ai/code (Remote Control). Then stop: do not start the mission, do not poll. When the user asks "how is it going", run `ms-workspace thanos sessions` (or `ms-workspace thanos status <batch>`); it only reads. Never type into the session unless the user asks: `ms-workspace tmux send` refuses while the session is not idle.

## `--from-brief <file>` (the session that `launch` started)
The user already confirmed everything in the launching session. Read the brief, **skip step 1 (the question round) and step 2 (the batch exists and you start inside its worktree, in the workspace or under `~/.dynamia/thanos`)**, and go on from step 3. Do not ask anything, then or later. If the brief lacks a success criterion that can be checked, write the most reasonable one under `## Decisions` and go on.

## Steps

0. **Check plan usage**: `ms-workspace usage --check --need 20`. Exit 1 or 2: show the numbers and use `AskUserQuestion` (continue / smaller mission / stop). Also tell the user once if their sign-in is about to expire when you know it.
1. **Brief, one `AskUserQuestion` round** (skip what the request already answers): the goal in one sentence, the success criteria (each checkable with a command or a file), which repos, and the step cap. Do not ask anything else, then or later.
2. **Open the batch**: `ms-workspace thanos new <slug> [repos...]` (kebab-case slug from the goal; in a workspace it is `batch new thanos-<slug>`). Work only inside the worktree it prints (`working-trees/thanos-<slug>/<repo>`).
3. **Plan.** Write the success criteria and the task list in `<batch>/THANOS.md` (it already has the sections): `- [ ] [S|M|L] name: what`, short names, in dependency order, each task small enough to finish and test in one go (S about 2 steps, M 4, L 8; split anything bigger). Then `ms-workspace thanos estimate <batch>`.
4. **Opus review 1/3**: launch `dynamia:boss` with the goal, criteria, task list and the files the plan touches; ask whether the plan is complete, safe and in the right order, in at most 25 lines. Fix the plan with what it finds; record the verdict under Decisions.
5. **Start the mission**: `ms-workspace thanos start <batch> --goal "<goal>" --opus-used 1 [--max-steps N | --until-usage PCT]`. `--opus-used 1` records the review of step 4, which happened before the mission existed, so the counter and the cap of three stay true. When the user says to go on "until usage reaches X%", use `--until-usage X`: the percentage (5h or weekly, whichever is higher) is then the limit and the step cap only guards against a runaway loop. The default cap is 30 steps (the config key `[thanos] max_steps`); when the estimate is above the cap the command warns, so tell the user in one line and raise the cap only if they asked for it. From here the purple badge `[THANOS IS WORKING]` shows in the status line and the Stop hook keeps you going while tasks are open.
6. **Loop, one task at a time:**
   1. `ms-workspace thanos task start <name>` (creates `agent/<batch>/<name>` from the batch branch).
   2. Implement it; read the code the change touches first. Commit locally in small steps.
   3. `ms-workspace test t0` (without a workspace: the repo's own test command); on a failure give the printed output to `dynamia:test-triage` first and fix only what it points to. If an approach fails, write it under `## Failed attempts` and never repeat it.
   4. `ms-workspace thanos task done <name>` (merges it `--no-ff` into the batch branch, ticks the line in `THANOS.md`, and pushes the batch branch to origin every few tasks as a backup).
   5. After a milestone (a group of related tasks) run `ms-workspace test t1 <batch>`.
   - After the user allows what blocked a parked task: `ms-workspace thanos unblock <task>`. To see which prompted commands deserve a permanent rule: `ms-workspace thanos allow-suggest`.
   - Blocked by a guard or a missing permission: `ms-workspace thanos block --task <name> "<what and why>"` (it records the blocker and parks the task `[!]` in the ledger), then go to the next. Never retry the same command in a disguised form.
   - Waiting for a background agent (the Opus reviewer, or a `dynamia:runner` you launched with `run_in_background`): run `ms-workspace thanos wait [MINUTES]` first and then end your turn. While the window is open the Stop hook lets you stop without counting steps; the reviewer's notification wakes you up. Do not poll.
   - A conflict on `task done` leaves you on the task branch: rebase it on the batch branch, fix, run `task done` again.
7. **Finish**: when no `[ ]` task is left, run `ms-workspace test t1 <batch>`, check every success criterion with evidence (the command and its result), then run `dynamia:pre-review` over the batch and fix what it lists as `fix-first`, then **Opus review 2/3** (give it the `send-to-boss` areas) over the whole batch against the original goal. Fix what is real, then `ms-workspace thanos done`.
8. **Report** in the user's language, short, with the status marks of the global instructions (🟢 criterion passed with its command, 🔴 failed or blocked, 🟡 not verified or risk left, 🟣 decisions and mission steps) so it reads the same in the terminal and in the chat: the goal and whether each criterion passed (with the command), the commits and files changed (`git diff --stat` against the base), the steps and Opus reviews used, the parked tasks and blockers, and what is left. Say what was not verified. `thanos done` also writes `THANOS-REPORT.md`; point to it. Tell them the next step is theirs: `ms-workspace plan <batch>` and `/dynamia:ship`.

## Extending a finished mission
When the user wants more work on top of a mission that is `done`: run `ms-workspace thanos extend <batch> --check` (add `--skip-tests` only if the user says so) and show the result. Only when it passes, `ms-workspace thanos extend <batch> --goal "<what to add>" --opus-used 0` after the same brief and plan steps (new tasks in the fresh `THANOS.md`, Opus review 1/3 of the new plan). The previous mission's history is in `THANOS.g<N>.md`; read it, do not redo what it lists as done, and never repeat its Failed attempts. If the check fails, tell the user what is wrong; do not extend a mission that is paused or has open tasks (use `resume`).

## When the mission pauses
It pauses by itself at the step cap, at critical plan usage, or after three steps without progress, and writes a handoff. Say so in one line with the reason, starting with 🟡. To continue: `ms-workspace thanos resume <batch>` (raise the cap first with a new `thanos start` only if the user wants more steps). `ms-workspace thanos stop` cancels the mission and keeps the batch.

## Notes
- Status at any time: `ms-workspace thanos status`. The ledger `THANOS.md` is the memory that survives compaction: keep Decisions, Failed attempts and Blockers current.
- Configure it in `workspace.toml`: `[thanos] max_steps`, `max_opus`, `push_every` (0 turns the backup push off) and `deny_hosts = ["prod.example.com"]` (a command that names one of them is blocked).
- Commands that are not on the known-safe list still go through the user's normal permissions, so allowlist the build and test commands of the repo to run unattended.
