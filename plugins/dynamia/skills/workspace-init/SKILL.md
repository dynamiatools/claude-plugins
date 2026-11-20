---
name: workspace-init
description: Creates or updates a dynamia workspace in a .dynamia folder - inside a git repo a one-repo workspace, elsewhere it asks which repos to include, clones the missing ones, detects stacks and base branches, and writes workspace.toml without overwriting an existing CLAUDE.md. Use when the user wants to set up a workspace, add a repo to one, bootstrap a new machine or move an older workspace into .dynamia. Triggers on "crea un workspace", "agrega este repo al workspace".
---

# dynamia:workspace-init

Builds a **workspace**: a `.dynamia/` folder with a `workspace.toml` that the rest of the workflow reads (batches, integration, shipping), for the repo you are in or for several related repos. It works from zero: no folder, no repos, no config.

Token rule: do the mechanical work with the bundled script, ask the user only
what cannot be detected, and keep every question short.

## Layout

```
<project>/
├── CLAUDE.md
├── api/  web/  ...           the repos (multi-repo workspace), in the project folder
└── .dynamia/
    ├── workspace.toml        the config
    └── workspace/            working-trees/ (the batches), logs/, images/, memory/ and the rest of the tool's files; never the repos
```

`<project>` is either the repo you are standing in (one-repo workspace) or a new folder (multi-repo workspace). Older workspaces keep `workspace.toml` and everything in one folder, and 0.4/0.5.0 put the clones inside `.dynamia/workspace/`; both still work, and `ms-workspace migrate` moves what needs moving.

## Steps

1. **Detect where we are.** Run `ms-workspace project` (JSON: `in_repo`, `project`, `workspace` = `new` / `old` / `none`, `claude_md.exists|managed`, `excluded`).
   - `workspace` is `new`: *update mode*. Read `<project>/.dynamia/workspace.toml` and change only what the user asks.
   - `workspace` is `old`: update mode on the old file, then offer `ms-workspace migrate` (dry run first; it refuses while batches are open).
   - `none` and `in_repo` is true: **one-repo workspace** (step 2a).
   - `none` and `in_repo` is false: **multi-repo workspace** (step 2b).

2a. **One-repo workspace.** The project is the repo's top-level folder. Ask only: workspace name (default: the folder name), base branch (suggest from `detect-repo.sh`), task tracking (`local` recommended; see Notes). Then:
   - Run `ms-workspace exclude`: it adds `.dynamia/` to the repo's `.git/info/exclude` (local, nothing tracked, shared by every worktree). Tell the user it is local to this clone and that a new clone needs the same command.
   - Write `.dynamia/workspace.toml` with one repo entry using `path = "."` (the repo is the project folder itself).
   - Skip steps 3 and 5's dependency questions.

2b. **Multi-repo workspace.** Ask in one `AskUserQuestion` round: workspace name and project folder (suggest `~/IdeaProjects/<name>`, create it if missing), which repos (GitHub `org/repo`, full URLs, or names of repos already present; free text), task tracking. Clone what is missing into `<project>/<repo>` (never inside `.dynamia/`); confirm first if there are more than 3 repos or credentials are needed, report failures verbatim and continue.

3. **Detect each repo** with the bundled script (one JSON per repo, tiny output):
   ```bash
   bash "${CLAUDE_PLUGIN_ROOT}/skills/workspace-init/scripts/detect-repo.sh" "<repo folder>"
   ```
   It returns the remote URL, default branch, suggested base branch (`next` if it exists), stacks (maven, gradle, pnpm, npm, yarn, go, python, rust) and a suggested test command.

4. **Show one compact table** (repo, base, stacks, test command) and ask only what is still unknown, in as few questions as possible:
   - Base branch per repo, only if the suggestion looks wrong.
   - **Dependencies** between repos (multi-repo only). Hint: shared SNAPSHOT versions in a `pom.xml`, or workspace/`file:` dependencies in `package.json`, usually reveal them.
   - **Release branches** per repo (e.g. `qa`, `main`), or none.
   - **e2e**: the command and the repo that owns it, or "none yet".
   - Whether the base branch accepts direct push (default: yes).
   - Optional, only if the user brings them up: `env = ["NAME=value"]` per repo (never secrets) and `[ide]` (`default`, `code`, `idea`).

5. **Write `<project>/.dynamia/workspace.toml`** following `${CLAUDE_PLUGIN_ROOT}/skills/workspace-init/references/workspace.example.toml`.
   - Do not write a `root` key: the workspace is located by the `.dynamia/` folder, so the file works on any machine.
   - For stacks with module-level selection, set `test.affected` (Maven: `-pl {modules} -amd`; pnpm: `pnpm --filter "...[origin/<base>]" test`). Otherwise reuse the full test command.
   - Never invent dependencies or e2e commands; leave `deps: []` / omit `e2e` if the user does not know.
   - Create `.dynamia/workspace/` if it does not exist yet.

6. **CLAUDE.md, respecting what is there.** Look at `claude_md` from step 1:
   - It does not exist: run `ms-workspace claude-md` from the project folder; it writes a short managed block (repos, agent rules, batch flow, token and tool guidance) between `ms-workspace:begin/end` markers.
   - It exists and is the repo's own (`managed` is false): **do not touch it.** Ask with `AskUserQuestion`: "This repo already has a CLAUDE.md. Optimize it by adding the workspace block at the end?" Offer: add the block (recommended; show `ms-workspace claude-md --print` first if the user wants to see it), or leave the file as it is. Only on yes run `ms-workspace claude-md --append`. Everything the user wrote stays.
   - It exists with the managed block: `ms-workspace claude-md` refreshes only the block, no question needed.

7. **Ignore.** One-repo: step 2a already excluded `.dynamia/`. Multi-repo: the project folder is not a repo, nothing to ignore. Mention that archived images under `.dynamia/workspace/images/` can contain sensitive data.

8. **Report**: path of `workspace.toml`, the dependency order, what was cloned, whether CLAUDE.md was created, extended or left alone, and what was left blank.

## Notes

- **Update mode** must never overwrite user edits: read the current file, change
  only the requested keys, write it back.
- **Task tracking**: `ask` makes the batch skill ask where each task list goes and confirm local ones. `local` keeps tasks in a small `TASKS.md` inside the batch
  folder, which agents read cheaply. `github` uses one tracking issue per
  batch (not per repo) to limit `gh` calls and tokens. Use it only when other
  people need visibility.
- This skill never pushes, opens PRs or changes remote branches.
- The workspace file contains no secrets: only URLs, branch names and commands.
