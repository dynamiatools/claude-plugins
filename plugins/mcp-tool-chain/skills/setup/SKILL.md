---
name: setup
description: Configures which MCP servers and which of their tools the tool-chain server may call. Use when the user installs mcp-tool-chain, wants to add or remove a server, open a write tool, or when describe says no servers are configured.
---

# Configure mcp-tool-chain

The config is `~/.config/mcp-tool-chain/servers.json` (or the file in `$MCP_TOOL_CHAIN_CONFIG`). Read it first if it exists; never overwrite it blindly.

```json
{
  "timeout": 120,
  "require_sandbox": false,
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
1. Ask which MCP servers to chain. Only stdio servers work (a `command`). Remote or OAuth servers are not supported yet.
2. Copy the `command`, `args` and `env` from the user's existing MCP config for that server. Do not print token values back; tell the user the file holds them and should stay out of git.
3. Read-only tools (those the server marks `readOnlyHint`) are callable by default. Add a tool to `allow` only when the user asks for it by name; `"*"` opens every tool of that server, so confirm it once.
4. Set `"require_sandbox": true` if the script must never run without network isolation. Check with the user first: on machines that block unprivileged user namespaces (for example Ubuntu 24.04 with AppArmor) it makes every run fail.
5. Tell the user to restart Claude Code or run `/reload-plugins`, then check with `describe`.
