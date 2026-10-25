# CLAUDE.md: the dynamia-tools marketplace

This repo is a Claude Code plugin marketplace (`dynamia-tools`, remote `dynamiatools/claude-plugins`). Each folder in `plugins/` is a separate, installable plugin. This file is how we create, update and manage them. A plugin's own README and CLAUDE.md win on that plugin's details.

## Layout
```
.claude-plugin/marketplace.json     catalog, one entry per plugin (name, source, description)
README.md                           public table of plugins; keep it in step with the catalog
plugins/<name>/
├── .claude-plugin/plugin.json      name, version, author, description, license, homepage, repository
├── skills/<skill>/SKILL.md         skills, called /<plugin>:<skill>
├── agents/*.md                     optional helper agents
├── hooks/hooks.json                optional hooks (commands use ${CLAUDE_PLUGIN_ROOT}/bin/...)
├── bin/                            scripts the hooks and skills call
├── tests/                          the plugin's own suite
├── README.md  LICENSE              NOTICE too when it adapts third-party material
```

## Rules for every plugin
- **Independent, with optional pointers.** A plugin works fully on its own: everything it needs ships inside its folder, and it never calls another plugin's scripts or reads its config. It may *point* to a sibling plugin's skill in text, only as an optional extra: say "if `<plugin>` is installed (its skills are listed as `/<plugin>:<skill>`), use `/<plugin>:<skill>`; otherwise suggest `/plugin install <plugin>@dynamia-tools`". Never make a pointer a required step, never depend on a sibling's output format, and recommend an install at most once per topic.
- **English** in code, docs, skills and commit messages. Chat with the user may be Spanish.
- **Small and cheap.** Short skills, no hooks unless they pay for themselves. A hook is silent outside its context, fails open, has a short timeout, and blocks only a case that is unmistakable.
- **Skill front matter** has `name` (equal to its folder) and a `description` that says what it does and when to use it. Avoid an unquoted `: ` inside the value. The plugin name is already the prefix: name the skill `test`, not `ms-test`.
- **Scripts.** `plugins/dynamia`: Python 3.11+, standard library only (`ms-workspace`). `plugins/dynamia-platform`: POSIX `sh`, no dependencies. Mark a deliberate shortcut with a `shortcut:` comment saying when to revisit it.
- **Third-party material.** Adapt, do not copy whole. Keep its license, credit it in `NOTICE` and in the README, and say what changed.
- **Never commit** secrets, tokens, or generated files (`__pycache__`, build output).

## Create a plugin
1. Branch from an up-to-date `master`: `feat/<plugin-name>`.
2. Plan first when it is more than a few files: goal, skills, hooks, what is out of scope. Read the sources you adapt; do not write from memory.
3. Create `plugins/<name>/` with the layout above. Start at version `0.1.0`. Copy `LICENSE` from another plugin.
4. Add the entry to `.claude-plugin/marketplace.json` and a row to the table in `README.md`, with the real counts of skills and hooks.
5. Write tests for anything with a branch, parser or script (hooks included). Skill text is checked by reading it and by `validate`.
6. Verify (below), commit, push, open the PR.

## Update a plugin
- Bump `version` in `plugin.json` when behavior changes: patch for fixes and wording, minor for new skills, hooks or flags (while below 1.0). Users only get an update when the version changes.
- Keep these in step with the change: the plugin README, the counts in the root README table, and `marketplace.json` description if the purpose changed. In `plugins/dynamia`, `settings/hooks.example.json` must match `hooks/hooks.json` (the suite compares them).
- Verify against the real thing, not memory: if a skill cites an API or a command, check it exists in the source (for `dynamia-platform`, the `dynamiatools/framework` repo).
- Try it live before the PR when the change affects how Claude behaves: `claude --plugin-dir plugins/<name>`, then `/reload-plugins` after edits.

## Verify before every commit and PR
```bash
claude plugin validate plugins/<name>        # the plugin manifest
claude plugin validate .                     # the marketplace
cd plugins/<name> && python3 -m unittest discover -s tests
```
`plugins/dynamia` runs about 375 tests in roughly three minutes: run it in the background or only when you touch that plugin. A report of finished work names the commands run and their result, and says what was not verified.

## Git and releases
- Branches: `feat/<topic>`, `fix/<topic>`, `docs/<topic>`. One topic per branch and per PR; a change that touches several plugins is several PRs unless it is a single README fix.
- Commits: imperative subject, a short body saying why. Commit locally as you go.
- **Push and open PRs only when the user says so**, after confirming the repo (`dynamiatools/claude-plugins`) and target branch (`master`). Merging is done by the user. Direct pushes to `master` only if the user asks for it explicitly, and only for docs.
- PR body: Summary, Verification (commands and results), Not verified.
- After a merge: update local `master`, delete the merged local branches (ask first).
- Do not modify the user's live environment (`~/.claude`, settings) while working here; test installers against a temporary `HOME`.

## Remove or rename a plugin
Removing: delete `plugins/<name>/`, its marketplace entry and README row, and say in the PR that installed copies keep working until the user uninstalls. Renaming changes the install name and every `/<plugin>:<skill>` command: avoid it, or do it with a note in the README.

## Where each plugin's details live
- `plugins/dynamia/README.md`: the workflow, which skills need a workspace and why. `plugins/dynamia/REFERENCE.md`: batches, worktrees, hooks, `ms-workspace` commands, setup, and the longest "add a skill / agent / hook" guide.
- `plugins/dynamia-craft/README.md`: the six working-discipline skills.
- `plugins/dynamia-platform/README.md`: Dynamia Platform skills, `dp-detect`, hooks.
