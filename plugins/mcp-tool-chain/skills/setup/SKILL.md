---
name: setup
description: Configures which MCP servers and which of their tools the tool-chain server may call. Use when the user installs mcp-tool-chain, wants to add or remove a server, open a write tool, or when describe says no servers are configured.
---

# Configure mcp-tool-chain

The server already imports the stdio MCP servers found in `~/.claude.json`, the project's `.mcp.json` and `.vscode/mcp.json`, Claude Desktop and Cursor. Call `describe` first: it shows what was found, what is callable and what is not. Only write a config when something has to change.

The config is `~/.config/mcp-tool-chain/servers.json` (or the file in `$MCP_TOOL_CHAIN_CONFIG`). Read it first if it exists; never overwrite it blindly. Entries in `servers` win over imported ones with the same name, so to open a write tool of an imported server, add `{"servers": {"<name>": {"command": ..., "args": [...], "allow": ["tool"]}}}` copying its command from the original config.

```json
{
  "timeout": 120,
  "require_sandbox": false,
  "import": ["claude", "project"],
  "exclude": ["some-server"],
  "servers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "..."},
      "allow": ["create_issue"]
    }
  }
}
```

Steps
1. Run `describe` and show the user what was imported. Ask only about changes. Only stdio servers work (a `command`); remote or OAuth servers are not supported yet. `import` limits the sources (`desktop`, `cursor`, `vscode`, `claude`, `project`), `false` turns it off, `exclude` drops a server by name.
2. For a server that is not imported (for example one bundled in a plugin), copy its `command`, `args` and `env` into `servers`. Do not print token values back; tell the user the file holds them and should stay out of git.
3. Read-only tools (those the server marks `readOnlyHint`) are callable by default. Add a tool to `allow` only when the user asks for it by name; `"*"` opens every tool of that server, so confirm it once.
4. Set `"require_sandbox": true` if the script must never run without network isolation. Check with the user first: on machines that block unprivileged user namespaces (for example Ubuntu 24.04 with AppArmor) it makes every run fail.
5. Tell the user to restart Claude Code or run `/reload-plugins`, then check with `describe`.
