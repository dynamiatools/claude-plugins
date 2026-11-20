---
name: node
description: Downloads, lists, loads and removes Node.js versions (npm and npx included) from nodejs.org into ~/.toolchains/node, or into the repo and git-ignored when the user asks. Use when a Node or npm version is missing, a project needs another major, or the user wants Node without a version manager. Triggers on prompts like "install node 20", "instala node lts" or "necesito npm".
---

# Node.js and npm

Official builds from nodejs.org, checked against its published SHASUMS256. Folder: `~/.toolchains/node`, or `<repo>/.toolchains/node` with `--project`. npm and npx come inside each Node version; pnpm and yarn come through corepack: `python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain node run NAME -- corepack enable pnpm` stays inside that version's folder.

## Steps

1. **Pick the version**: the project's `.nvmrc`, `.node-version`, `package.json` `engines.node` or Volta settings first; otherwise `lts`. `python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain node available` lists recent releases.
2. **Ask where** only when it matters: default `~/.toolchains/node`; `--project` only when the user asks for it inside the repo (adds `.toolchains/` to `.gitignore`, `--no-ignore` skips that, and it shows in `git status`).
3. **Install**: `python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain node install lts|latest|22|22.11.0 [--project]`. Report the exact version it picked.
4. **Load it.** Each Bash call of Claude Code starts a fresh shell, so an `eval` does not last. For a command you run, use `run`:
   `python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain node run NAME -- npm ci`
   For the user's own terminal give them the line to paste: `eval "$(python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain node env NAME)"` (`env --unload NAME` undoes it; `--shell fish|powershell` for other shells). Do not edit their shell files.
5. **Report** the name, the folder and how it was loaded. Say what you did not check (for example that the build still passes with it).

## Notes

- `python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain node run NAME -- npm test` puts that Node's `bin` first in `PATH` for one command.
- Check what is installed: `python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain node list`. Remove: `python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain node remove NAME --yes`, only after the user confirms.
- Linux and macOS only (x64 and arm64). Everything downloads over https from the tool's official site, and a checksum mismatch installs nothing.
- The tool does not edit shell startup files, `PATH` outside the command it runs, or the user's own `~/.cargo`, `~/.nvm` or similar folders.
