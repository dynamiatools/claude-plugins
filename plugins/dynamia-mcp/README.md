# dynamia-mcp

Five small MCP servers that answer in one call what the agent would otherwise ask with many commands and long output. Python 3.11+, standard library only, stdio. They are written to be chained with [`mcp-tool-chain`](../mcp-tool-chain), but work as plain MCP servers too.

| Server (`bin/`) | Tools | Writes? |
|---|---|---|
| `gh_lite.py` | `issue_state(numbers)`, `pr_status(number)`, `checks(number)`, `issues_closed_by(number)`: compact JSON from the `gh` CLI | no |
| `repo_map.py` | `symbols(file)`, `callers(name)`, `changed_since(ref)`, `tests_for(file)`: lookups through git, no whole-file reads | no |
| `git_overview.py` | `repos`, `worktrees`, `stashes`: branch, ahead/behind, dirty count, last commit, here or one level below | no |
| `test_runner.py` | `run(command, cwd, timeout)`: runs a test command and returns the exit code, the summary line and only the failing tests; a build error returns its first problem lines and the tail | runs project code |
| `board.py` | `list(state)`, `set(updates)`, `clear`: the issues in progress, kept per repo | its own file |

Only `test_runner.run`, `board.set` and `board.clear` are not marked read-only, so a chain needs them in `allow`.

## Use them
Add the servers you want to `mcp-tool-chain`'s `servers` (use the real path of the installed plugin), or to a `.mcp.json`:
```json
{
  "mcpServers": {
    "gh":    { "command": "python3", "args": ["<plugin>/bin/gh_lite.py"] },
    "repo":  { "command": "python3", "args": ["<plugin>/bin/repo_map.py"] },
    "git":   { "command": "python3", "args": ["<plugin>/bin/git_overview.py"] },
    "tests": { "command": "python3", "args": ["<plugin>/bin/test_runner.py"] },
    "board": { "command": "python3", "args": ["<plugin>/bin/board.py"] }
  }
}
```
They work in the project the agent was started in. `DYNAMIA_ROOT` overrides that folder. Each tool description costs context when the server is listed directly, so prefer the chain: one `describe`, then one script.

A chain that settles the board after merges:
```python
open_ = [i["n"] for i in tools.board.list() if i["state"] != "done"]
closed = [i["n"] for i in tools.gh.issue_state(numbers=open_) if i.get("state") == "CLOSED"]
tools.board.set(updates=[{"n": n, "state": "done"} for n in closed])   # needs "allow": ["set"]
print(closed)
```

## Limits
- `board` is its own list (`~/.local/state/dynamia-mcp/board/<owner>__<repo>.json`, `DYNAMIA_STATE` overrides). It does not read or write the pane of `issue-board`; the plugins stay independent.
- `gh_lite` needs `gh` installed and logged in; `DYNAMIA_GH` names another binary.
- `repo_map.symbols` reads declarations by regex (java, kotlin, groovy, python, ts/js, go). It is a map, not a parser.
- `test_runner` accepts only known runners (mvn, gradle, bun, npm, pnpm, yarn, npx, vitest, jest, pytest, python, go, cargo, dotnet) and keeps `cwd` inside the project. It runs whatever the project's tests run: not a sandbox.

## Tests
```
cd plugins/dynamia-mcp && python3 -m unittest discover -s tests
```
Uses a fake `gh` and temporary git repos; no network.
