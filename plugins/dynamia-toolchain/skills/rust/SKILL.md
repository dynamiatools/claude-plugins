---
name: rust
description: Installs, lists, loads and removes Rust toolchains (cargo, rustc) into ~/.toolchains/rust through the official rustup-init, without touching shell files, or into the repo and git-ignored when the user asks. Use when cargo or rustc is missing or a crate needs a specific Rust version. Triggers on prompts like "install cargo", "instala rust" or "necesito rustc".
---

# Rust and cargo

Downloads `rustup-init` from static.rust-lang.org, checks the sha256 it publishes, and runs it with its own `CARGO_HOME` and `RUSTUP_HOME` inside `~/.toolchains/rust/rust-<toolchain>` (or `<repo>/.toolchains/rust` with `--project`) and `--no-modify-path --profile minimal`, so the user's `~/.cargo`, `~/.rustup` and shell files are never touched. Running the installer is the one place a downloaded program runs: say that to the user before you do it.

## Steps

1. **Pick the toolchain**: `rust-toolchain.toml` or `rust-version` in `Cargo.toml`; otherwise `stable`. `python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain rust available` lists the channels.
2. **Ask where** only when it matters (default home; `--project` adds `.toolchains/` to `.gitignore`).
3. **Install**: `python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain rust install stable|beta|nightly|1.82.0 [--project]`. The minimal profile has cargo and rustc; extra components are `python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain rust run NAME -- rustup component add clippy rustfmt`.
4. **Load it.** Each Bash call of Claude Code starts a fresh shell, so an `eval` does not last. For a command you run, use `run`:
   `python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain rust run NAME -- cargo test`
   For the user's own terminal give them the line to paste: `eval "$(python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain rust env NAME)"` (`env --unload NAME` undoes it; `--shell fish|powershell` for other shells). Do not edit their shell files.
5. **Report** the name, the folder and how it was loaded. Say what you did not check (for example that the build still passes with it).

## Notes

- `python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain rust run NAME -- cargo build` sets `CARGO_HOME`, `RUSTUP_HOME` and puts cargo first in `PATH`.
- Check: `python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain rust list`. Remove: `python3 ${CLAUDE_PLUGIN_ROOT}/bin/toolchain rust remove NAME --yes` after the user confirms.
- Linux and macOS only (x64 and arm64). Everything downloads over https from the tool's official site, and a checksum mismatch installs nothing.
- The tool does not edit shell startup files, `PATH` outside the command it runs, or the user's own `~/.cargo`, `~/.nvm` or similar folders.
