---
name: run
description: Chains several MCP tool calls in one Python script with the tool-chain server, so only the final result enters the context. Use when a task needs three or more dependent MCP calls, loops over many items, or filters big results before answering.
---

# Run a chain of MCP tool calls

Use the `describe` and `run` tools of the `tool-chain` MCP server (shown as `mcp__tool-chain__describe` and `mcp__tool-chain__run`).

1. Call `describe` once. It lists the callable tools as Python signatures. If it says no servers are configured, point the user to `/mcp-tool-chain:setup` and stop.
2. Write the shortest script that does the whole job and call `run` with it:
   ```python
   issues = tools.github.search_issues(query="is:open label:bug")
   old = [i for i in issues if i["age_days"] > 30]
   for i in old[:5]:
       print(i["number"], i["title"])
   print(len(old), "old of", len(issues))
   ```
3. Print only what the answer needs. Everything the script prints is read back; everything it does not print stays out of the context.

Rules
- Use it for chains and loops. A single call is cheaper made directly with the MCP tool.
- Results arrive parsed (dict, list or text). A failed tool raises `ToolError`; catch it only when the script can go on without that call.
- Standard library only. There is no network from the script when the host allows isolation, and the run output says when it does not.
- A tool missing from `describe` is not callable (write tools are hidden by default). Do not work around that; tell the user it needs `allow` in the config.
- Do not put secrets in a script. The server holds the credentials of the upstream servers.
