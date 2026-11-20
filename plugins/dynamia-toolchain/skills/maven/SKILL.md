---
name: maven
description: Downloads, lists, loads and removes Apache Maven versions into ~/.toolchains/maven, or into the repo and git-ignored when the user asks. Use when mvn is missing, a project needs a specific Maven version, or there is no mvnw wrapper. Triggers on prompts like "install maven", "instala maven 3.9" or "no tengo mvn".
---

# Apache Maven

Official releases from Apache, checked against the published sha512. Folder: `~/.toolchains/maven`, or `<repo>/.toolchains/maven` with `--project`. Prefer the project's `./mvnw` when it has one; install Maven only when it does not. Maven needs a JDK: if none is loaded, offer `/dynamia-toolchain:jdk`.

## Steps

1. **Pick the version**: what `.mvn/wrapper/maven-wrapper.properties` or the project's docs name; otherwise `latest` (stable only, never a release candidate). `python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain maven available` lists the recent lines.
2. **Ask where** only when it matters (default home; `--project` adds `.toolchains/` to `.gitignore`).
3. **Install**: `python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain maven install latest|3|3.9|3.9.9 [--project]`.
4. **Load it.** Each Bash call of Claude Code starts a fresh shell, so an `eval` does not last. For a command you run, use `run`:
   `python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain maven run NAME -- mvn -v`
   For the user's own terminal give them the line to paste: `eval "$(python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain maven env NAME)"` (`env --unload NAME` undoes it; `--shell fish|powershell` for other shells). Do not edit their shell files.
5. **Report** the name, the folder and how it was loaded. Say what you did not check (for example that the build still passes with it).

## Notes

- `python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain maven run NAME -- mvn -q verify` puts that Maven first in `PATH` and sets `MAVEN_HOME`.
- Check: `python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain maven list`. Remove: `python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain maven remove NAME --yes` after the user confirms.
- To use it with a JDK installed here, nest `run`: `python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain jdk run JDK_NAME -- python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain maven run NAME -- mvn -v`.
- Linux and macOS only (x64 and arm64). Everything downloads over https from the tool's official site, and a checksum mismatch installs nothing.
- The tool does not edit shell startup files, `PATH` outside the command it runs, or the user's own `~/.cargo`, `~/.nvm` or similar folders.
