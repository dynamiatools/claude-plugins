---
name: jdk
description: Downloads, lists, loads and removes JDKs of any distribution (Temurin, Corretto, Zulu, GraalVM, Liberica, Microsoft and more) into ~/.jdks, or into the repo and git-ignored when the user asks. Use when a JDK or a Java version is missing, when a build needs another distribution, or when JAVA_HOME must point somewhere else. Triggers on prompts like "install java 17", "instala java 17 en el repo", "usa Corretto 21" or "necesito un JDK".
---

# JDKs, any distribution

Uses the Foojay Disco API, the catalog behind SDKMAN and IntelliJ, so any distribution works. Folder: `~/.jdks` (IntelliJ IDEA finds JDKs there), or `<repo>/.jdks` with `--project`.

## Steps

1. **See what exists** only if the user did not name it: `python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain jdk available` (maintained versions and the distributions) and `python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain jdk available DISTRO` (what one distribution offers for this machine). Default to Temurin and the newest LTS when the user has no preference, and say so; use the project's own version when a `pom.xml`, `build.gradle`, `.sdkmanrc` or `.java-version` names one.
2. **Ask where** only when it matters: the default is `~/.jdks`. Use `--project` only when the user asks for the JDK inside the repo; it adds `.jdks/` to the repo's `.gitignore` (`--no-ignore` skips that). Mention that the `.gitignore` change will show in `git status`.
3. **Install**: `python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain jdk install DISTRO VERSION [--project]` where VERSION is a major (`21`), `lts` or a full version (`21.0.5`). It prints the exact build it picked: report it. The checksum is verified; if it fails nothing is installed.
4. **Load it.** Each Bash call of Claude Code starts a fresh shell, so an `eval` does not last. For a command you run, use `run`:
   `python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain jdk run NAME -- mvn -q test`
   For the user's own terminal give them the line to paste: `eval "$(python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain jdk env NAME)"` (`env --unload NAME` undoes it; `--shell fish|powershell` for other shells). Do not edit their shell files.
5. **Report** the name, the folder and how it was loaded. Say what you did not check (for example that the build still passes with it).

## Notes

- `python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain jdk run NAME -- ./mvnw -q verify` sets `JAVA_HOME` and puts the JDK first in `PATH` for that one command.
- Check what is installed: `python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain jdk list`. Remove: `python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain jdk remove NAME --yes`, only after the user confirms (it deletes the folder).
- If `JAVA_HOME` already points at another JDK, say so before switching. For Maven or Gradle builds also read what the project's toolchain files require.
- Linux and macOS only (x64 and arm64). Everything downloads over https from the tool's official site, and a checksum mismatch installs nothing.
- The tool does not edit shell startup files, `PATH` outside the command it runs, or the user's own `~/.cargo`, `~/.nvm` or similar folders.
