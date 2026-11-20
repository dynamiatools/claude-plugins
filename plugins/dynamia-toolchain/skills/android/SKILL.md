---
name: android
description: Installs the Android SDK command-line tools into ~/.toolchains/android, then adds SDK packages (platform-tools, platforms, build-tools) with sdkmanager, or inside the repo and git-ignored when the user asks. Use when adb, sdkmanager, ANDROID_HOME or an Android build is missing. Triggers on prompts like "install the android sdk", "instala el sdk de android" or "no tengo adb".
---

# Android SDK

Downloads Google's command-line tools from dl.google.com, checked against the sha1 its repository file publishes (it publishes no stronger one). Folder: `~/.toolchains/android/android-sdk` (`ANDROID_HOME`), or `<repo>/.toolchains/android` with `--project`. The SDK needs a JDK: if none is loaded, offer `/dynamia-toolchain:jdk` (17 or newer).

**Licenses are the user's to accept.** Never accept them for them and never pipe `yes` into `sdkmanager`. Tell them to run, in this prompt, `! sdkmanager --sdk_root=<ANDROID_HOME> --licenses` (the command is printed when a package install stops on a license).

## Steps

1. **Pick the packages** from the project: `compileSdk` and `buildToolsVersion` in the Gradle files, `ndkVersion` if present. Typical: `platform-tools`, `platforms;android-35`, `build-tools;35.0.0`.
2. **Ask where** only when it matters (default home; `--project` adds `.toolchains/` to `.gitignore`).
3. **Install the tools**: `python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain android install [--project]`, then the packages: `python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain android sdk 'platform-tools' 'platforms;android-35' 'build-tools;35.0.0'`. If sdkmanager stops on licenses, hand the `--licenses` step to the user and run the packages again afterwards.
4. **Load it.** Each Bash call of Claude Code starts a fresh shell, so an `eval` does not last. For a command you run, use `run`:
   `python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain android run NAME -- ./gradlew assembleDebug`
   For the user's own terminal give them the line to paste: `eval "$(python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain android env NAME)"` (`env --unload NAME` undoes it; `--shell fish|powershell` for other shells). Do not edit their shell files.
5. **Report** the name, the folder and how it was loaded. Say what you did not check (for example that the build still passes with it).

## Notes

- `python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain android run android-sdk -- adb devices` sets `ANDROID_HOME` and `ANDROID_SDK_ROOT` and puts `sdkmanager` and `platform-tools` first in `PATH`.
- Check: `python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain android list`. Remove: `python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain android remove android-sdk --yes` after the user confirms (it deletes every package inside).
- To use it with a JDK installed here, nest `run`: `python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain jdk run JDK_NAME -- python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain android run android-sdk -- ./gradlew assembleDebug`.
- Google marks `sdkmanager` as deprecated in favour of a newer `android` command in the same folder; this plugin uses `sdkmanager`, which still works.
- Linux and macOS only (x64 and arm64). Everything downloads over https from the tool's official site, and a checksum mismatch installs nothing.
- The tool does not edit shell startup files, `PATH` outside the command it runs, or the user's own `~/.cargo`, `~/.nvm` or similar folders.
