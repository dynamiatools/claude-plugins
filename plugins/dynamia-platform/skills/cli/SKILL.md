---
name: cli
description: Checks, installs and uses the Dynamia Platform CLI (@dynamia-tools/cli, command `dynamia`) to scaffold a new project with backend (Java/Kotlin/Groovy) and Vue or React frontend. Use when the user wants to create a new Dynamia project, install or update the CLI, or asks whether Node, Java or the CLI are ready.
---

# dynamia-platform:cli

The CLI has one command today: `dynamia new`. Any other command answers "not available yet" (`DT-COMMAND-001`). There is no generator for entities, views or endpoints yet: write those by hand with `dynamia-platform:backend`.

## 1. Check the toolchain
```bash
dynamia --version; node -v; java -version 2>&1 | head -1; git --version
```
Needs: CLI, Node >= 24, git, and JDK 25 (recommended). `${CLAUDE_PLUGIN_ROOT}/bin/dp-detect --facts` prints `cli`, `node` and `java` among other facts.

### Keep the CLI current
Run `${CLAUDE_PLUGIN_ROOT}/bin/dp-cli-update` before using the CLI (and whenever the user asks if it is up to date). It prints `status=current|outdated|missing|unknown installed=X latest=Y`, comparing with npm.
- `outdated`: update it without asking, with `${CLAUDE_PLUGIN_ROOT}/bin/dp-cli-update --apply` (it runs `npm install -g @dynamia-tools/cli@latest`, never `sudo`). Say in one line `dynamia X -> Y`. If it exits 1 because npm's global folder needs `sudo`, show the message and let the user decide.
- `missing`: follow step 2 (plan first, then confirm).
- `unknown` (offline or no npm): say the latest version could not be checked and continue with the installed one.

## 2. Install what is missing (plan first, then confirm)
- **Only the CLI is missing and Node >= 24 exists:** `npm install -g @dynamia-tools/cli`. Show the command and ask before running it.
- **Node, JDK or git are missing:** use the official bootstrap, but never pipe it straight into a shell. Download it, read it, and tell the user what it does:
  ```bash
  mkdir -p ~/.cache/dynamia-platform && curl -fsSL https://get.dynamia.tools -o ~/.cache/dynamia-platform/install.sh
  ```
  The script installs git/curl/zip with `sudo` (apt, dnf, pacman or brew), JDK 25 through SDKMAN, Node LTS through fnm, **adds init lines to the shell profile** (`~/.bashrc`, `~/.zshrc` or `~/.profile`), installs the CLI, and **ends by launching the interactive `dynamia new` wizard**. Linux and macOS only.
  Do not run it yourself: the wizard needs a terminal and would hang. Ask the user to run it, or to run it with `! bash ~/.cache/dynamia-platform/install.sh` so the output lands in the session. Afterwards a new shell may be needed for `node`/`java` to appear on PATH; re-run the checks in step 1.
- Check with the user before touching anything outside `$HOME` or using `sudo`.

## 3. Create a project: always with flags
Without every flag `dynamia new` opens an interactive prompt and the session hangs (a hook blocks that case). Ask only for what the user has not said, then pass everything:

| Flag | Values | Default to suggest |
|---|---|---|
| `--name` | lowercase letters, digits, hyphens | none, ask |
| `--scaffold` | `both`, `backend`, `frontend` | `both` |
| `--backend-lang` | `java`, `kotlin`, `groovy` | `java` |
| `--group-id`, `--artifact-id` | Maven coordinates | `com.example`, the name |
| `--version`, `--description` | text (`--description ''` for none) | `1.0.0-SNAPSHOT` |
| `--frontend`, `--pm` | `vue` or `react`; `pnpm`, `npm`, `yarn` | `vue`, `pnpm` |
| `--yes` | skip the confirmation | always |
| `--git` / `--no-git` | initialize git in the project | ask |

Backend flags are only needed when scaffold is `both` or `backend`; frontend flags when it is `both` or `frontend`. Some templates may be disabled ("not available yet"); the error says which.

```bash
dynamia new --name shop --scaffold both --backend-lang java --group-id com.acme --artifact-id shop \
  --version 1.0.0-SNAPSHOT --description '' --frontend vue --pm pnpm --yes --no-git
```
It creates `./<name>/` with `backend/` (Spring Boot + Dynamia, cloned from a GitHub template and renamed) and `frontend/` (Vue/React + Vite + `@dynamia-tools/sdk` + `ui-core`). It needs network and git. Run it from the parent folder, never inside an existing project.

## 4. After generating
Report the folder and what was created, then `cd` there and check `dp-detect`. Build/run commands come from the generated README: read it, do not guess. Errors carry codes like `DT-TEMPLATE-002`: quote them verbatim.

## Not verified here
The CLI is in beta and its behavior was read from its source (`platform/packages/cli`), not run. `dp-cli-update` is tested against a fake `npm`, not against the real registry. If a flag is rejected, trust `dynamia new --help` / the error over this table.
