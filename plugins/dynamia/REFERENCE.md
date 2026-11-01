# dynamia: reference

Details for people who use or change the plugin. The short guide (the workflow, which skill does what, which ones need a workspace) is in the [README](README.md).

## Install without the plugin

`install.sh` (needs a clone) does the same linking without the skill, for use without the plugin or on a machine where you prefer a script:
- It is idempotent and uses symlinks, so this repo stays the single source of truth.
- Files that already exist are moved to `~/.claude/backups/my-claude-<timestamp>/`, never deleted. Your own `~/.claude/CLAUDE.md` is replaced by the one in this repo (backed up first).
- `--legacy` also links skills and agents into `~/.claude`, for use without the plugin (the skills then have no `dynamia:` prefix and the hooks come from `/dynamia:setup` without `--plugin-root`).
- `--uninstall` removes only links that point to this repo. `CLAUDE_HOME` and `BIN_DIR` redirect the targets (defaults `~/.claude` and `~/.local/bin`; make sure `BIN_DIR` is in your `PATH`).
## The batch workflow

Everything stays local until `ship`. Agents commit locally and never push.

| Step | Command | What happens |
|---|---|---|
| 1 | `batch new <batch> [repos]` | One worktree per repo on `int/<batch>`, branched from the base branch (for example `next`). Ignored files a fresh worktree lacks (`.env`, secrets) are copied from the main checkout; tracked files never are |
| 2 | `agent new <batch> <task> [repos]` | Optional isolated worktree per parallel agent (`agent/<batch>/<task>`), so agents never touch the same files |
| 3 | `test t0` | Tests only what changed in the current repo. A pass is remembered by a hash of the code and command, so repeating it is instant (`--no-cache` forces a run) |
| 4 | `integrate <batch> [--dry-run]` | Merges the agent branches into `int/<batch>` in dependency order and names conflicting files. `--dry-run` checks each branch against `int/<batch>` only, not against each other |
| 5 | `test t1 <batch>` | Affected modules plus the repo's `critical` modules, for each changed repo |
| 6 | `plan <batch>` | Shows what would be sent: per repo the target branch, push mode, commit subjects and a diffstat. Refuses while agent branches are not integrated |
| 7 | `ship <batch>\|--branch [repo] --yes [--pr\|--direct]` | `--branch` ships the task branch checked out in a repo's own checkout (the plain-branch path of `/dynamia:batch`) with the same steps, and leaves the branch in place. Merges a moved base branch, re-runs t1, runs the `[e2e]` command (or `--skip-e2e`), then pushes `int/<batch>` to the base branch (`push = "direct"`) or opens a PR (`push = "pr"`, needs `gh`). `--pr` forces a PR for that run in every repo, whatever its `push` setting (`plan <batch> --pr` previews it); it is what "open a PR" means to `/dynamia:ship`. `--direct` forces a direct push the same way. With `push = "ask"` a repo has no default: `plan`/`ship` refuse until the run says `--pr` or `--direct`, so the agent asks you first. For a big change `plan`/`ship` print `RECOMMEND A PR` (defaults: 20 files, 800 lines or 10 new files, tunable in `[ship]`); it is advice only, the mode never changes by itself and the agent relays it and lets you choose. Never targets a `release` branch, never force-pushes |
| 8 | `undo <batch> [--yes]` | Reverts the last ship: every `ship --yes` records what each base branch pointed to before and after. `undo` shows the plan; with `--yes` it pushes one new commit per repo that restores the previous tree (history kept, never a force-push). If someone else pushed in the meantime it refuses for that repo and prints the exact `git revert` commands; in `pr` mode it prints how to close the PR. Works after `clean` too |
| 9 | `clean [<batch>]` | Lists batches, or removes one whose branch is in its base branch **and** whose agent branches are all integrated; otherwise it refuses and names them (`--force` discards on purpose) |

`ms-workspace open <batch> [--ide code|idea] [--repo R] [--agent TASK] [--dry-run]` opens the batch's real worktree paths in an IDE and never touches Git (no checkout, commit, merge or push). VS Code gets one generated `<workspace>/ide/<batch>.code-workspace` (outside every repo, rewritten only when it changes), so search and Git see only that batch; IntelliJ opens each worktree as its own project, because it recognizes Maven/Gradle modules only from the opened directory's own `pom.xml`/`build.gradle` (use `--repo` for one window; ignore `.idea/` in the repo, or `ship` sees it as uncommitted). `--agent TASK` opens that agent's worktrees. The launcher is found on `PATH` (and the JetBrains Toolbox scripts), or set it in `workspace.toml`: `[ide]` with `default = "code"`, `code = "..."`, `idea = "..."`. `open` is in `ask` because it runs a configured command.

A repo can set `env = ["NAME=value", ...]` in `workspace.toml`; those variables are added to its `test`, `[e2e]` (the e2e repo's) and `env --setup` commands. A changed value invalidates the remembered test pass, a malformed entry stops with a clear error. The file is shared and committed, so keep secrets in `env_files` instead.

Names are validated, and a failed `batch new` or `agent new` rolls back what it created. `ms-workspace env [batch] [--setup] [--trust]` re-copies ignored files, runs each repo's `setup` command and marks worktrees as trusted so background agents skip the trust dialog.

## Guardrails

- **Permissions are narrow on purpose.** `allow` covers read-only and local subcommands (`status`, `log`, `usage`, `plan`, `test`, `integrate`, `batch new`, ...). `ship`, `undo`, `clean`, `env`, `setup-hooks`, `docker clean`, `ps kill`, `notify` and `http run|bench` are in `ask`, so Claude Code always prompts before anything is pushed, deleted or run from configuration. `setup-hooks` replaces an older broad `Bash(ms-workspace:*)` rule.
- **The guard** (`ms-workspace guard`, a PreToolUse hook) blocks `git push`, `gh pr create|merge`, `gh api` writes, `ms-workspace undo|clean --force|setup-hooks` (plain `clean <batch>` is allowed: it only removes a batch already merged into origin), `ship --skip-gate`, `ps kill`, `docker clean` and `env --trust` **inside batch worktrees** (`env --setup` is allowed there so an agent can install dependencies with the repo's own `setup` command; it stays in `ask`, so the user approves it) (`ms-workspace ship` itself is allowed there: it is the sanctioned way to publish, it stays in `ask`, and the `/dynamia:ship` skill shows the plan and that permission prompt is the single confirmation), including option variants, `bash -c`, `eval`, wrappers and `cd` into a batch from elsewhere. It fails closed: inside `working-trees/` (`.batches/` in older layouts) it decides from the command text alone, so a broken `workspace.toml` cannot open the gate. It stops mistakes and realistic variants, not a determined adversary. Blocked attempts are logged.
- **Plan usage.** Claude Code exposes the 5h session and weekly usage only to the status line, so `ms-statusline` stores a snapshot and `ms-workspace usage` reads it: percent used and left, time to reset, pace, projection and a verdict. `usage --check` exits 0 ok, 1 warn, 2 critical, 3 no data, so skills and agents confirm with you before starting; `--need <pct|auto>` checks that a planned task fits (`auto` uses the median of past completed batches, at least 3). Thresholds come from `[usage]` in `workspace.toml` (default 70/90). Projections only influence the verdict above 50 % used. Pro/Max plans only; data appears after the first reply of a session.
- **Token-saving hooks.** `readguard` (PreToolUse on Read) tells Claude when it is about to re-read an unchanged file that is already in its context (files under 4 000 characters are ignored; a compaction or `/clear` resets the memory, because re-reading is legitimate then). `outguard` (PostToolUse on Bash) replaces a Bash output longer than 30 000 characters with its first and last 60 lines, saves the full text to a file it names, and keeps `stderr` and the output shape. Tune it with `[context] bash_output_max_chars`, `MS_OUTGUARD_MAX_CHARS`, or turn it off with `MS_OUTGUARD=off`. Neither hook can fail a session.
- **Memory.** The log says what happened; `ms-workspace memory` keeps what was learned: one markdown note per fact (`decision`, `lesson`, `gotcha`, `handoff`) with `add`, `list`, `search`, `show`, `forget`. If an agent must stop early it leaves a handoff for the next session; `context` shows only a count and the latest handoff of each active batch, so it costs a few tokens. Handoffs disappear with their batch.

## Observability

- **`context`** (SessionStart hook) injects a short briefing: active batches, open tasks, plan usage, memory and handoffs, last actions. It prints nothing outside a workspace.
- **`log [-n N] [--day D] [--action A]`**: one JSON line per action in `<workspace>/logs/` (`<workspace>` is `.dynamia/workspace/`; older layouts keep it in `.ms-workspace/logs/`), one file per day, pruned after `log_retention_days` (default 14). Test events carry duration, a code hash and the plan usage at that moment.
- **`budget [--top N] [--json]`**: what every session loads before you type anything, in tokens (estimate: characters / 4, an upper bound): global and workspace `CLAUDE.md` plus their imports, unscoped rules, the name and description of every skill and agent, Claude's auto-memory index and what `context` injects, with hints for the biggest items. Path-scoped rules are listed as on-demand, and MCP servers are counted but their tool schemas are not measurable from files.
- **`insights [--days N]`**: slow runs, flaky candidates (same code, both pass and fail), time per batch and an approximate plan cost per batch (usage jumps between a batch's events, so parallel work elsewhere is counted too).
- **`tokens [--days N]`**: reads Claude Code's local transcripts for sessions run inside the workspace and reports requests, new input, cache reads and output per batch or repo, the tools whose results were largest (characters divided by 4), repeated reads of one file, and hints. Everything stays local.
- **Pasted images.** Claude Code keeps chat images only as base64 inside the session transcript. `images capture` (Stop and SessionEnd hook) saves the new ones to `<workspace>/images/YYYY-MM-DD/HHMMSS_<session>_<n>.<ext>` with an `index.jsonl` (time, session, directory, the text sent with the image). Duplicates are skipped by hash, files older than `images_retention_days` (default 30) are pruned, `images [list]` shows recent ones and `images backfill` imports past sessions. They may contain sensitive data: they stay local, outside any repo.
- **`status [--fetch]`** (one line per repo), **`doctor`** (tools, versions, workspace, hooks, usage snapshot, resources), **`affected`** (changed modules and dependent repos).

## API checks

`ms-workspace http` runs requests described in `requests/*.http.toml` (in the workspace root, or any file path) with assertions, and logs every exchange. Copy `skills/workspace-init/references/requests/` as a starting point.

```bash
ms-workspace http run smoke --env local      # PASS/FAIL per request, exit 1 if anything failed
ms-workspace http run smoke --only login --var user=bob --tag smoke --fail-fast --json
ms-workspace http history                    # past runs
ms-workspace http show last [request]        # the failing exchanges (masked bodies, headers, timing)
ms-workspace http diff [runA] [runB]         # what changed vs the previous run: status, result, speed, JSON values
ms-workspace http bench smoke --name health -n 20   # min/avg/p50/p95/max; flags a p95 regression against the last bench
ms-workspace http list
```

- **Assertions** per request under `expect`: `status` (number or list), `max_ms`, `json` (dotted path to value, `items.0.id`), `json_exists`, `body_contains`, `body_not_contains`, `headers`. Without `status`, only 4xx and 5xx fail.
- **Chaining**: `capture = { token = "json:access_token" }` (also `header:`, `regex:`, `status`) feeds `{{token}}` into later requests. A request whose variable has no value is skipped, not guessed.
- **Variables**: `requests/env/<env>.toml` (committed, plain values), `--var k=v`, captured values, `{{env:NAME}}` from the process environment, `{{secret:NAME}}` from `requests/env/<env>.secrets` (dotenv, keep it out of git) or the environment.
- **Secrets stay out of logs and output**: `{{secret:...}}` values, sensitive headers (`Authorization`, `Cookie`, `*token*`, `*password*`, `*api-key*`), such JSON keys in request and response bodies, and such query parameters are replaced by `***`. The log is `<workspace>/http/YYYY-MM-DD.jsonl`; bodies are cut at 4 000 characters. Outside a workspace the log goes to `~/.cache/ms-workspace/http/`.
- **Safety**: an environment file with `confirm = true` (qa, prod) refuses to run without `--yes` and refuses `bench`. Redirects are not followed unless a request sets `follow_redirects = true`; `insecure = true` accepts self-signed certificates. Permissions: `list`, `history`, `show`, `diff` are allowed; `run` and `bench` always ask, because they send traffic.
- **Smoke checks before shipping**: `[http] smoke = "smoke"` and `smoke_env = "local"` in `workspace.toml` make `ship --yes` run that collection after t1 and before e2e; a failure blocks the push (`--skip-smoke` bypasses it deliberately). `plan` shows the line.

## Local tools: mock server, Docker, system, processes

**Mock server** (`ms-workspace mock`). A local stand-in for third-party APIs (payments, tax authority) that records every call, so you can test without the real service and then assert what your code sent. Definitions live in `mocks/*.mock.toml` (example: `skills/workspace-init/references/mocks/`).

```bash
ms-workspace mock start payments        # background server on 127.0.0.1 (free port, or port = N / --port N); --restart reloads the file
ms-workspace mock url payments          # feed it to the app, or: ms-workspace http run smoke --var base_url=$(ms-workspace mock url)
ms-workspace mock requests --unmatched  # what was received (masked); -n, --path, --method
ms-workspace mock assert --path /v1/payments --method POST --times 1 --json amount=100   # exit 1 with the closest candidates if it does not hold
ms-workspace mock status | list | stop [--all]
```

Routes match top to bottom (method, `{param}` or trailing `*` path, optional `match` on JSON body, query and headers). Responses: `status`, `json` or `body`, `headers`, `delay_ms`, and `sequence` for retries and flaky providers (the last step repeats, or cycles with `loop = true`). Templates `{{path.id}}`, `{{query.x}}`, `{{body.a.b}}`, `{{header.x}}`, `{{seq}}`, `{{uuid}}`, `{{now}}`; a value that is exactly one placeholder keeps its JSON type. Requests that match no route get a 404 and are recorded, so `assert --no-unmatched` catches calls you did not plan for. The log masks secrets like the `http` tool does.

**Docker** (`ms-workspace docker`), compact and read-only except `clean --yes`:

| Command | What it shows |
|---|---|
| `status [-a] [--project P]` | One line per container (image, state, short ports, compose project), plus unhealthy and stopped ones |
| `logs <c> [-n N] [--since 10m] [--errors]` | Last lines with timestamps stripped and repeats collapsed (`(x37)`); `--errors` keeps only error-like lines |
| `stats` | CPU and memory per container, heaviest first, flagged above 80 % |
| `disk` | Space by images, containers, volumes and build cache, and how much is reclaimable |
| `health <c...>` | Health state, last three check outputs, restarts, exit code, OOM kill |
| `ports`, `env <c>` | Published ports; environment variables with sensitive values masked |
| `wait <c...> [--timeout 120]` | Blocks until healthy (or running, when there is no healthcheck); exit 1 on failure or timeout |
| `clean [--until 24h] [--yes] [--volumes]` | Plan of stopped containers and dangling images; `--yes` prunes them; volumes only with `--volumes` |

**System** (`ms-workspace sys [--tools] [--json]`): OS, kernel, uptime, CPU and load per core, memory and swap, disks (root, `/tmp`, the workspace), network address, timezone, and with `--tools` the versions of git, gh, python, node, java, maven, gradle, docker and others. It adds a hint when memory is under 10 % available, swap is over half used, load per core is above 1.5 or a disk is nearly full. Linux first; macOS is best effort.

**Processes** (`ms-workspace ps`):

| Command | What it does |
|---|---|
| `ps [--top N] [--by cpu\|mem] [--mine] [--filter text]` | Heaviest processes (CPU is `ps`'s average since start) |
| `ps tree <pid\|text>`, `ps find <text>` | A process with its children; processes whose command contains the text |
| `ps ports [--port N] [--all]` | Listening TCP ports with their owner, and which workspace batch it runs in; `--port 8080` answers "who holds it" |
| `ps leftovers [--hours 4] [--limit 20]` | Dev processes (java, node, mvn, python, cloudflared...) that are old or orphaned, labelled with the batch they run in |
| `ps kill <pid...> [--signal TERM] [--yes]` | Plan first. Refuses other users' processes, this session and its parents, pid 1, and protected ones (systemd, sshd, tmux, claude); `--yes` sends the signal and checks that it worked |

`clean` refuses to remove a batch while a process still runs inside it (`--force` overrides with a warning). On a shared server, `ps`, `docker` and `sys` only ever act on what the current user may touch.

## Safety, quality and knowledge tools

| Tool | What it does |
|---|---|
| `gate [batch]` | Scans the **added lines** of what would be sent for secrets (AWS, GitHub, Slack, Stripe, Google, JWT, private keys, credentials in URLs, hard-coded passwords and tokens), merge-conflict markers (only when both ends are present) and files over `max_file_kb`; debug leftovers (`console.log`, `debugger`, `.only(`, `System.out`, `printStackTrace`, `pdb`) are warnings, matched by language and spared in test files. Evidence is masked, placeholders and `word:word` values are not flagged, `ms-gate: allow` or `[gate] allow`/`ignore_paths` silence deliberate cases. `ship` runs it and stops on blocking findings (`--skip-gate` bypasses on purpose); works in a plain repo too |
| `junit [paths] [--since MIN]` | Summarizes JUnit-style XML (Surefire/Failsafe, Gradle, vitest/jest-junit, pytest): totals, failing tests grouped by message, the first stack frame that is not framework code. When a test run fails and fresh reports exist, `test` prints this instead of the log tail and keeps the full output in `<workspace>/tests/` (`reports = [globs]` per repo to override discovery) |
| `modules [deps\|rdeps <m>\|closure\|check]` | Reads the Maven reactor (modules declared at the top or inside profiles, inherited coordinates, `${properties}`): dependents of a change, the exact `closure` for `-pl` (also in `affected` and as `{closure}` in test commands), cycles, and `[[arch.rule]]` checks such as "depend on `api`, never on another module's `core`". On the real ERP it maps 131 modules in 0.2 s |
| `recall <words>` | Full-text search (SQLite FTS5) over Claude Code sessions run in the workspace, memory notes and the log: "where did we decide X?". Secrets are masked before indexing, the index refreshes itself incrementally, results point to `claude --resume <id>` |
| `handoff` | Writes the state needed to resume a batch (commits ahead, uncommitted files, unintegrated agent branches, open tasks, next step). Hooks write it by themselves before compaction and at session end, and on Stop when plan usage is high; one note per batch, unchanged state is not rewritten |
| `promote [repo] [--to BRANCH] [--yes] [--direct]` | Promotes the base branch to a release branch listed in `release = [...]`: a PR `base -> release` by default (needs `gh`), or with `--direct` a fast-forward push (refused when the release branch has commits the base lacks; never forced). Works on origin's refs only, no checkout or worktree is touched; plan only without `--yes`; `--to` is required when a repo has several release branches. Local unpushed commits on the base are not promoted (the plan warns). Tests are not re-run (they passed at `ship`; the PR is where CI runs). No undo: revert with a PR. Blocked inside batch worktrees |
| `release status\|notes [repo]` | Per repo with `release = [...]`: commits waiting to be promoted from the base branch, grouped by conventional-commit type, authors, diffstat, breaking changes, and hotfix drift (commits that exist only on `qa`/`main`); `notes` prints markdown by type |
| `notify <msg>` | ntfy, webhook or a local command from `[notify]`; as a Notification hook it forwards "Claude needs your attention", and `on = ["ship"]` announces ship results. Nothing is configured by default, secrets are masked, repeats within 30 s are sent once, only `http(s)` URLs are accepted. A public ntfy topic can be read by anyone who guesses it |

## The workspace

A workspace lives in a `.dynamia/` folder inside your project; the project folder keeps only `CLAUDE.md`:

```
<project>/
├── CLAUDE.md
├── api/  web/  ...         the repos (multi-repo workspace), in the project folder
└── .dynamia/
    ├── workspace.toml      config (see skills/workspace-init/references/workspace.example.toml for every key)
    └── workspace/          working-trees/ (the batches), logs/, images/, memory/ and the rest of the tool's files; never the repos
```

`/dynamia:workspace-init` first checks where you are (`ms-workspace project`):
- **Inside a git repo**: a one-repo workspace. The repo is the project folder (`path = "."` in `workspace.toml`), and `.dynamia/` is added to the repo's `.git/info/exclude` (`ms-workspace exclude`): local to this clone, nothing tracked, and shared by every worktree, so the repo and its batch worktrees stay clean in `git status`. A new clone needs `ms-workspace exclude` once.
- **Outside a repo**: a multi-repo workspace; the clones go to `<project>/<repo>`, next to `.dynamia/`, which only keeps the config and what the tool generates.
- **The repo's own `CLAUDE.md` is respected**: it is never edited unasked. The skill asks whether to add the workspace block at the end (`ms-workspace claude-md --append`); with a block already there, only the block is refreshed.

Older workspaces (`workspace.toml` and everything in one folder) and the clones that 0.4/0.5.0 left inside `.dynamia/workspace/`, and the `.batches/` and `.ms-workspace/` dot folders of 0.6.0, keep working; `ms-workspace migrate` shows the move and `migrate --yes` applies it (it refuses while batches are open, because worktrees store absolute paths).

Things to know in a one-repo workspace: `git clean -fdx` in the repo also deletes ignored files, so it would wipe `.dynamia/` (plain `-fd` is safe); and tools that scan the whole tree without reading `.git/info/exclude` (pytest, jest, an IDE indexer) can see the batch copies under `.dynamia/workspace/working-trees/`, so exclude that folder there.

```toml
name = "shop"
tasks = "local"                     # or "github" or "ask" (the agent asks where to keep them); a repo can override it
[repos.framework]
base = "next"
[repos.framework.test]
unit = "mvn -T1C -B test"
affected = "mvn -T1C -B test -pl {modules} -amd"
[repos.erp]
base = "next"
deps = ["framework"]
critical = ["sources/modulos/modulo-pagos"]   # always tested in t1
[e2e]
command = "docker compose -f e2e/docker-compose.yml up --abort-on-container-exit"
repo = "erp"
```

`ms-workspace claude-md` generates `<workspace>/CLAUDE.md` (repos in dependency order, agent rules, the flow, token and tool guidance, taken from `[tools]`). Only the block between the `ms-workspace:begin/end` markers is managed, so your notes around it survive every regeneration. The Tasks section also tells agents to use the DynamiaTasks MCP (`mcp__dynamia-tasks__*`, [dynamiatools/dynamia-tasks](https://github.com/dynamiatools/dynamia-tasks), in development) when it is available; without it nothing changes. Without `[tools] discovery` the tool list names only what is installed (the graph when `codebase-memory-mcp` is on `PATH`, then Grep/Glob/Read); the IDE tools appear only if you list them. `claude-md --refresh` (offered after installing or removing `codebase-memory`) rewrites the file only when it is entirely generated; a CLAUDE.md with your own text is never touched.

## Development environment variables

Local-development variables live in `.dynamia/workspace.toml`, in tables of their own (`[dev.env]` for every repo, `[repos.<r>.dev.env]` for one, which wins). They are applied to the commands the workspace runs: `test` (t0, t1, t2), the e2e command and `env --setup`. A changed value invalidates a cached passing test. Plain text, for local use only.

```bash
ms-workspace dev-env add API_URL=http://localhost:8080            # every repo
ms-workspace dev-env add DEBUG=1 --repo erp                        # one repo
ms-workspace dev-env list [--show|--json]  /  rm NAME [--repo R]   # names that look secret are shown as ***
```

Three ways in: `/dynamia:dev-env` (Claude asks which variables and registers them), the `ms-workspace` commands above, and the **dev-env panel**, a mod of this plugin: `/dynamia-env-panel` opens a pane (terminal and desktop, 110+ columns) with the current variables, fields for NAME and value, a repo picker and Add / remove buttons; `/dynamia-env-panel NAME=value [repo]`, `/dynamia-env-panel rm NAME [repo]` and `/dynamia-env-panel list` work everywhere, including the mobile app, which has no input fields yet. The mod is `hooks/register.tsx` (named in `hooks/hooks.json` under `modules`, next to the command hooks); it only calls `ms-workspace dev-env`, which stays the single writer of the file. Two more panels from the same mod (`hooks/panels.tsx`): `/dynamia-logs-panel` shows the latest `ms-workspace log` actions with a Refresh button, and `/dynamia-memory-panel` browses the memory notes, adds one (type + text) and forgets one with ✕.

## Hooks

With the plugin, the hooks load from `hooks/hooks.json` (paths use `${CLAUDE_PLUGIN_ROOT}`), so nothing is copied into `settings.json` except the status line and permissions: `/dynamia:setup` (or `ms-workspace setup-hooks --plugin-root <plugin folder> [--dry-run] [--remove] [--project]`) does that, and removes an older copy of the hooks so they do not run twice. Without the plugin, `ms-workspace setup-hooks` merges `settings/hooks.example.json` instead: idempotent, keeps every other hook, permission and setting, keeps a status line someone else configured, writes a timestamped backup. It adds `handoff --hook` (PreCompact, Stop, SessionEnd), `notify --hook` (Notification), `guard` and `readguard` (PreToolUse on Bash and Read), `outguard` (PostToolUse on Bash), `images capture` (Stop, SessionEnd), `context` (SessionStart), `readguard --reset` (SessionStart after `/clear` or a compaction), `ms-statusline` and the permission rules above. `install.sh` never edits your `settings.json` by itself.

## Development

- Everything in the repo is in English; skills and agents have no prefix (the plugin name is it) and the command-line tools use `ms-`; no secrets or machine-specific paths.
- `ms-workspace` stays standard-library only. The CLI is the contract: `tests/` drives the real tool (bare remotes, worktrees, conflicts, hooks, usage snapshots, images, installer, skill frontmatter).

```bash
# from plugins/dynamia/
python3 -m unittest discover -s tests            # about 45 s; throwaway repos and a private HOME
python3 -m unittest tests.test_ms_workspace.TestShip -v
```

`MS_WORKSPACE_BIN` runs the suite against another build of the tool.

**Add a skill**: create `skills/<name>/SKILL.md` with `name` and `description` frontmatter (avoid an unquoted `: ` in values, the suite checks it), write clear trigger conditions in `description`, test it with `claude --plugin-dir .` (it reloads with `/reload-plugins`), run `claude plugin validate .`, commit. The plugin name is the prefix, so name it plainly (`test`, not `ms-test`). Agents are one file each in `agents/`, also without prefix. Hooks go in `hooks/hooks.json`; keep `settings/hooks.example.json` in step, the suite compares them.

## Roadmap

- [x] API checks (`ms-workspace http`) with assertions, masked logs, diff and bench
- [x] Local mock server, Docker views, system information and process tools
- [ ] First end-to-end run on real repos (Maven, pnpm, Gradle) and a live check of the image hook
- [x] Secret gate, JUnit summaries, Maven module graph with architecture rules, recall, automatic handoff, release view and notifications
- [ ] Exact integration plan across agents (merge-tree chain) instead of per-branch `--dry-run`
- [ ] `clean` recognising squash-merged PRs in `pr` mode
- [ ] Import the remaining personal skills and agents from `~/.claude`
