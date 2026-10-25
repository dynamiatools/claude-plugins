# dynamia

**The way we work with Claude Code at [Dynamia](https://dynamiasoluciones.com), packaged as a plugin.**

AI coding gets expensive and risky when the model does the boring parts: juggling git across repos, re-running tests, re-reading the same files. This plugin is a workflow that takes those parts away from the model and puts guard rails around the risky ones.

- **Let a tool do the plumbing.** `ms-workspace` handles git, tests and bookkeeping, so the model spends tokens thinking, not running `git status`.
- **Work in batches.** Each task gets its own copy of the repos; nothing half-done reaches your main checkout.
- **Guard the dangerous stuff.** Hooks block secrets, pushes from agents and runaway output.
- **Spend tokens on purpose.** Cheap helper agents search and summarize; reports show where the plan went.
- **Humans publish.** Agents commit locally. You decide what ships.

It has 19 skills, 4 read-only helper agents, guard hooks, a standard-library Python tool (`ms-workspace`) and a status line.

## Install

```
/plugin marketplace add dynamiatools/claude-plugins
/plugin install dynamia@dynamia-tools
```

Then, in a **new** session, run `/dynamia:setup` once. A plugin cannot set your status line, permissions or `~/.claude/CLAUDE.md`, so this skill does it: it shows a preview, asks, makes a backup, adds the status line and permission rules, the global instructions (`~/.claude/DYNAMIA.md`) and puts `ms-workspace` in `~/.local/bin`. `ms-workspace doctor` checks the result; `/dynamia:setup --remove` undoes it. Updates need no new setup (`/plugin update dynamia`).

## The workflow

```
once per machine   once per project        per task                                    when you say so
 /setup             /workspace-init   ->   /batch  ->  work  ->  /test  ->  /integrate  ->  /ship
                    (workspace.toml)       worktrees   agents     t0         merge + t1      gate, sync,
                                                                                              push or PR
```

1. **Set up the workspace (once per project): `/dynamia:workspace-init`.** Writes `.dynamia/workspace.toml`: the repos, their base branches, dependency order and test commands. *Why:* every other skill reads this one file, so none of them has to guess how to test or where to push.
2. **Open a batch (per task): `/dynamia:batch`.** Creates one isolated git worktree per repo on a branch `int/<batch>`. For a small, one-repo task on a clean checkout it can recommend a plain branch instead, and it asks you. *Why:* your main checkout stays clean, and several tasks can run side by side.
3. **Work.** Optionally give each parallel agent its own worktree (`ms-workspace agent new`), so agents never edit the same files. While you work, `/dynamia:test` runs **t0** (only what changed; a pass is remembered, so repeating it is instant) and triages failures. `/dynamia:dev-env` registers the environment variables the tests need.
4. **Join the agents' work: `/dynamia:integrate`.** Merges the agent branches into `int/<batch>` in dependency order, names conflicting files, then runs **t1** (affected modules plus the ones marked critical). *Why:* conflicts show up locally, before anything is published.
5. **Ship, only when you ask: `/dynamia:ship`.** Shows the plan (target branch, commits, diffstat), asks, then scans for secrets (`/dynamia:gate`), merges a moved base branch, re-runs t1 and the end-to-end command and pushes or opens a PR. Never force-pushes, never targets a release branch. *Why:* publishing is the one step that stays human. The permission prompt of `ship` is the confirmation.
6. **Afterwards.** `ms-workspace undo <batch>` reverts the last ship with a new commit; `ms-workspace clean` removes finished batches.

Day to day, around the flow: `/dynamia:report` (plan usage, where tokens went, flaky tests), `/dynamia:memory` and `/dynamia:recall` (notes and past sessions), `/dynamia:release` (what waits for qa or main), `/dynamia:open` (a batch in your IDE).

## Skills

### They need a workspace
These read `workspace.toml`. Without one the tool answers `no .dynamia/workspace.toml found`; run `/dynamia:workspace-init` first. A one-repo workspace is enough (it is made inside a git repo and ignored locally).

| Skill | What it does | Why it exists |
|---|---|---|
| `/dynamia:workspace-init` | Creates or updates the workspace: finds repos, clones missing ones, detects stacks and base branches | The single entry point; the rest of the flow depends on its config |
| `/dynamia:batch` | Starts a batch: one worktree per repo | Isolation: no task touches a shared checkout |
| `/dynamia:test` | Runs t0 (changed), t1 (whole batch) or t2 (end to end); triages failures | Cheap, cached test levels so the model does not run or read whole suites |
| `/dynamia:integrate` | Merges agent branches into the batch, reports conflicts, runs t1 | Makes parallel agents safe |
| `/dynamia:ship` | Plan, sync, tests, push or PR. Only when you ask | Controlled publishing in one place |
| `/dynamia:dev-env` | Registers dev environment variables per repo or for all | Tests and e2e run with the right variables, kept out of the model's hands |
| `/dynamia:open` | Opens a batch or an agent's worktrees in VS Code or IntelliJ | Review the work where you are used to reading code |
| `/dynamia:memory` | Saves and finds durable notes: decisions, lessons, gotchas, handoffs | The log says what happened; notes say what was learned |
| `/dynamia:recall` | Full-text search over past sessions, notes and the log | "Where did we decide X?" without re-reading transcripts |
| `/dynamia:release` | What waits to go from the base branch to qa or main; release notes | Release prep without manual git archaeology |
| `/dynamia:report` | Plan usage and pace, where tokens went, slow or flaky tests | Spend the plan on purpose. Usage works without a workspace; the per-batch history needs one |

### They work anywhere

| Skill | What it does | Why it exists |
|---|---|---|
| `/dynamia:setup` | Installs or removes the status line, permissions and global instructions | Things a plugin cannot configure by itself |
| `/dynamia:gate` | Scans what would be sent for secrets, conflict markers, huge files and debug leftovers | Read-only; works in a plain repo too, and `ship` runs it for you |
| `/dynamia:http` | API checks with assertions, and local mock servers for third-party APIs | Test endpoints and integrations without the real service. Smoke checks before shipping need a workspace |
| `/dynamia:git-status` | Compact status card of the current repo | A quick, read-only look at where things stand |
| `/dynamia:sys` | Machine load, disk, memory, ports and leftover processes | Find who holds a port or what was left running |
| `/dynamia:tmux-session` | Starts a tmux session with Claude Code and Remote Control in a project | Work from another device |
| `/dynamia:code-tunnel` | Opens a Cloudflare tunnel to the remote code viewer for the current repo | Share a read-only view of the code |
| `/dynamia:powers-installers` | Installs, checks and removes agent helpers (uv, rtk, codebase-memory, graphify, headroom); shows the plan first | One reviewed script instead of ad-hoc installs |

## Agents

Read-only helpers. The first three run on Haiku so the main model does not spend tokens on reading and summarizing.

| Agent | Use |
|---|---|
| `dynamia:scout` | Finds where code lives: paths and one line each |
| `dynamia:test-triage` | Classifies a failing run (code, test, flaky, environment, config, build) and points to the file |
| `dynamia:summarizer` | Condenses diffs, history and logs; drafts commit messages in each repo's style |
| `dynamia:boss` | Opus architecture review of a batch, diff or design: verdict, blocking and should-fix findings |

## Guard rails

They work without being invoked.

- **Narrow permissions.** Reading and local commands are allowed. `ship`, `undo`, `clean`, anything that deletes or runs from configuration always asks.
- **The guard.** Inside a batch, agents cannot `git push`, open or merge PRs, or kill processes, including through `bash -c`, `eval` or `cd`. It fails closed and logs every blocked attempt. It stops mistakes, not a determined adversary.
- **Token hooks.** `readguard` warns before re-reading an unchanged file; `outguard` cuts a Bash output over 30,000 characters to its first and last lines and saves the rest to a file.
- **Plan usage.** `ms-statusline` records the 5h and weekly usage; skills check it before long work and ask you when it is high.
- **Handoffs.** Before compaction and at the end of a session a note is saved, so the next session resumes where this one stopped.

## The workspace

```
<project>/
├── CLAUDE.md
├── api/  web/  ...        the repos (multi-repo workspace)
└── .dynamia/
    ├── workspace.toml     the config
    └── workspace/         working-trees/ (the batches), logs, memory; never the repos
```

- **Inside a git repo** it is a one-repo workspace. `.dynamia/` is excluded through `.git/info/exclude`, so the repo stays clean.
- **Outside a repo** it is a multi-repo workspace; the clones go next to `.dynamia/`.
- The repo's own `CLAUDE.md` is never edited unasked.

```toml
name = "shop"
[repos.framework]
base = "next"
[repos.framework.test]
unit = "mvn -T1C -B test"
[repos.erp]
base = "next"
deps = ["framework"]
critical = ["sources/modulos/modulo-pagos"]   # always tested in t1
[e2e]
command = "docker compose -f e2e/docker-compose.yml up --abort-on-container-exit"
repo = "erp"
```

Every key is in `skills/workspace-init/references/workspace.example.toml`.

## More

- [REFERENCE.md](REFERENCE.md): every `ms-workspace` command, the full ship steps, API checks, mock server, Docker and process tools, observability, hooks, how to add a skill, and the roadmap.
- Tests: `python3 -m unittest discover -s tests` from this folder (about 45 s).

## License

[MIT](LICENSE), Copyright (c) 2026 Dynamia Soluciones.
