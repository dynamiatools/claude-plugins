# bg-output

A side pane, opened with `/bg-output`, that shows the live output of long-running background commands, so you can watch a Maven build, a Gradle run, a jar or a Node server without leaving the chat.

It is a mod (a hooks module), not a skill: it changes the interface and adds no skills or agents.

## How it works
- When Claude runs a Bash command in the background (or you send one there with Ctrl+B) and the command uses a watched program, it is tracked. The pane does **not** open by itself: type `/bg-output`. To open it automatically, turn on the `autoOpen` option (off by default).
- A command with `nohup` is not a background task of Claude Code, so the pane follows the log it writes instead: the last `>`, `>>` or `&>` target (`/dev/null` ignored), else `nohup.out`, relative to the shell's folder or a `cd dir &&` before it. Any `nohup` command counts, watched program or not.
- The pane keeps a fixed title with a colored `LIVE` or `IDLE` badge and the full command, a line per older command, and the tail of the output, refreshed every second.
- `IDLE` means no new output for 10 seconds. It is a hint, not proof that the process ended.
- It keeps the last 8 commands. Only the newest shows its output.

## Watched programs (default)
`mvn`, `mvnw`, `gradle`, `gradlew`, `java`, `node`, `npm`, `npx`, `pnpm`, `yarn`, `bun`, `deno`, `docker`, `cargo`, `go`, `python`, `python3`, `pytest`, `make`, `tsc`, `vite`, `webpack`.

Any word of the command counts, minus its directory, so `cd app && ./mvnw test` matches. Edit `WATCHED` in `hooks/watch.ts` to change the list.

## Install
```
/plugin install bg-output@dynamia-tools
```

## Limits
- The pane needs a wide terminal (about 110 columns or more); below that it waits undrawn.
- It reads the output file the background task writes (a path ending in `.output`). If a Claude Code version words that message differently, the pane does not open.

- A detached command that redirects through a variable or a subshell, or logs with `tee`, is not found.

## Tests
```
claude plugin test plugins/bg-output
```
