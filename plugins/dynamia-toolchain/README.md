# dynamia-toolchain

Download, check and switch the tools a project needs, from one place and without a version manager: **JDKs of any distribution, Node.js (with npm), Maven, Gradle, Go, Rust (cargo) and the Android SDK**.

Everything comes from the tool's official site and is installed only when the checksum that site publishes matches. Nothing edits your shell files or your own `~/.cargo`, `~/.nvm` and similar folders.

## Install

```
/plugin marketplace add dynamiatools/claude-plugins
/plugin install dynamia-toolchain@dynamia-tools
```

## Skills

| Skill | What it does |
|---|---|
| `/dynamia-toolchain:jdk` | Any JDK (Temurin, Corretto, Zulu, GraalVM, Liberica, Microsoft...) through the Foojay Disco API, into `~/.jdks` |
| `/dynamia-toolchain:node` | Node.js and npm from nodejs.org; pnpm and yarn through corepack |
| `/dynamia-toolchain:maven` | Apache Maven |
| `/dynamia-toolchain:gradle` | Gradle |
| `/dynamia-toolchain:go` | Go |
| `/dynamia-toolchain:rust` | cargo and rustc through the official `rustup-init`, in a folder of their own |
| `/dynamia-toolchain:android` | Android SDK command-line tools, then the packages you need; the user accepts the licenses |

## Where things go

- **Home** (default): `~/.jdks` for JDKs (IntelliJ IDEA finds them there) and `~/.toolchains/<tool>` for the rest.
- **The repo**, when you ask (`--project`): `<repo>/.jdks` or `<repo>/.toolchains/<tool>`, and the folder is added to `.gitignore` (`--no-ignore` skips that).
- Any other folder with `--where /path`.

## The script

```
python3 bin/toolchain tools
python3 bin/toolchain jdk available
python3 bin/toolchain jdk install temurin 21           # a major, "lts" or a full version
python3 bin/toolchain node install lts --project
python3 bin/toolchain go list
eval "$(python3 bin/toolchain jdk env temurin-21.0.5)"  # load it into your shell (env --unload undoes it)
python3 bin/toolchain maven run maven-3.9.9 -- mvn -v   # or just for one command
python3 bin/toolchain android sdk 'platform-tools' 'platforms;android-35'
```

Claude Code starts a fresh shell for every command, so for its own commands use `run` (nest it to combine tools: `jdk run NAME -- python3 bin/toolchain maven run NAME -- mvn -v`) and give you the `env` line for your terminal.

## Notes

- Standard library Python, written for 3.9 or newer (tested on 3.15). Linux and macOS, x64 and arm64. Windows is not supported.
- The Android repository publishes only a sha1 checksum; that is what is checked. `sdkmanager` is deprecated by Google in favour of a newer `android` command in the same folder, but still works.
- No hooks, no network use except the downloads you ask for. The base URL of each site can be overridden with `TOOLCHAIN_*_URL` variables (the tests use this to run offline).
- `rust install` runs the downloaded `rustup-init` (after its checksum matches), with its own `CARGO_HOME` and `RUSTUP_HOME`.
