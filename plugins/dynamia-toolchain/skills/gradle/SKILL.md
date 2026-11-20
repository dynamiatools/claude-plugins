---
name: gradle
description: Downloads, lists, loads and removes Gradle versions into ~/.toolchains/gradle, or into the repo and git-ignored when the user asks. Use when gradle is missing and the project has no gradlew, or a specific Gradle version is needed.
---

# Gradle

Official releases from services.gradle.org, checked against the published sha256. Folder: `~/.toolchains/gradle`, or `<repo>/.toolchains/gradle` with `--project`. Prefer the project's `./gradlew`; install Gradle only when it has no wrapper. Gradle needs a JDK: if none is loaded, offer `/dynamia-toolchain:jdk`.

## Steps

1. **Pick the version**: `gradle/wrapper/gradle-wrapper.properties` or the project's docs; otherwise `latest`. `python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain gradle available` lists the recent lines.
2. **Ask where** only when it matters (default home; `--project` adds `.toolchains/` to `.gitignore`).
3. **Install**: `python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain gradle install latest|8|8.10|8.10.2 [--project]`.
4. **Load it.** Each Bash call of Claude Code starts a fresh shell, so an `eval` does not last. For a command you run, use `run`:
   `python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain gradle run NAME -- gradle build`
   For the user's own terminal give them the line to paste: `eval "$(python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain gradle env NAME)"` (`env --unload NAME` undoes it; `--shell fish|powershell` for other shells). Do not edit their shell files.
5. **Report** the name, the folder and how it was loaded. Say what you did not check (for example that the build still passes with it).

## Notes

- `python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain gradle run NAME -- gradle test` puts that Gradle first in `PATH` and sets `GRADLE_HOME`.
- Check: `python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain gradle list`. Remove: `python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain gradle remove NAME --yes` after the user confirms.
- To use it with a JDK installed here, nest `run`: `python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain jdk run JDK_NAME -- python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain gradle run NAME -- gradle build`.
- Linux and macOS only (x64 and arm64). Everything downloads over https from the tool's official site, and a checksum mismatch installs nothing.
- The tool does not edit shell startup files, `PATH` outside the command it runs, or the user's own `~/.cargo`, `~/.nvm` or similar folders.
