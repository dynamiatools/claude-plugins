---
name: go
description: Downloads, lists, loads and removes Go toolchains into ~/.toolchains/go, or into the repo and git-ignored when the user asks. Use when go is missing, a module needs a specific Go version, or the user wants Go without a version manager. Triggers on prompts like "install go 1.23", "instala go" or "necesito golang".
---

# Go

Official builds from go.dev, checked against the sha256 in its download index. Folder: `~/.toolchains/go`, or `<repo>/.toolchains/go` with `--project`. The build sets `GOROOT` only; the user's `GOPATH` and module cache stay where they are.

## Steps

1. **Pick the version**: the `go` or `toolchain` line of `go.mod`; otherwise `latest`. `python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain go available` lists the newest patch of each minor.
2. **Ask where** only when it matters (default home; `--project` adds `.toolchains/` to `.gitignore`).
3. **Install**: `python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain go install latest|1.23|1.23.4 [--project]`.
4. **Load it.** Each Bash call of Claude Code starts a fresh shell, so an `eval` does not last. For a command you run, use `run`:
   `python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain go run NAME -- go test ./...`
   For the user's own terminal give them the line to paste: `eval "$(python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain go env NAME)"` (`env --unload NAME` undoes it; `--shell fish|powershell` for other shells). Do not edit their shell files.
5. **Report** the name, the folder and how it was loaded. Say what you did not check (for example that the build still passes with it).

## Notes

- `python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain go run NAME -- go build ./...` puts that Go first in `PATH` and sets `GOROOT`.
- Check: `python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain go list`. Remove: `python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain go remove NAME --yes` after the user confirms.
- Linux and macOS only (x64 and arm64). Everything downloads over https from the tool's official site, and a checksum mismatch installs nothing.
- The tool does not edit shell startup files, `PATH` outside the command it runs, or the user's own `~/.cargo`, `~/.nvm` or similar folders.
