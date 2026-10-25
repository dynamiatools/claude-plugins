# mcp-tool-chain

Chain many MCP tool calls in one short Python script. The model writes the script, a small MCP server runs it and calls the other MCP servers for it, and only what the script prints comes back. Intermediate results never enter the context.

The idea comes from Cloudflare's [Code Mode](https://blog.cloudflare.com/code-mode/) (the model writes code against a typed API instead of calling tools one by one). This is a local, smaller version: Python instead of TypeScript, a subprocess instead of V8 isolates.

## Install
```
/plugin install mcp-tool-chain@dynamia-tools
```
Then run `/mcp-tool-chain:setup` to choose the servers.

## What you get
- An MCP server `tool-chain` (`bin/chain-server`, Python 3.11+, standard library only) with two tools: `describe` (tool signatures) and `run` (execute a script).
- Two skills: `/mcp-tool-chain:setup` and `/mcp-tool-chain:run`. No hooks.

## How a script sees the tools
```python
rows = tools.sales.query(sql="select id, total from orders where day = '2026-10-23'")
big = [r for r in rows if r["total"] > 1_000_000]
tools.chat.post(text=f"{len(big)} big orders yesterday")   # needs "allow": ["post"]
print(len(rows), len(big))
```
Results arrive parsed; a failed tool raises `ToolError`. `tools["server"]["tool"]` also works. Names are made safe (`echo-text` becomes `echo_text`).

## Safety, honestly
- **Allow list.** A tool is callable only if the server marks it read-only (`readOnlyHint`) or you list it in `allow`. The check runs in the server, not in the script.
- **Credentials stay in the server.** The script runs with an empty environment and never sees the upstream servers' tokens.
- **Limits.** Timeout (default 120 s), output cap (20,000 bytes), script size cap.
- **Network.** When `unshare -rn` works, the script runs without network. Some systems block that (Ubuntu 24.04 with AppArmor); there the script runs with network and the run output says so. Set `"require_sandbox": true` to refuse instead.
- **Not a security boundary.** The script can still read your files with your permissions. Calls made through the server skip Claude Code's per-tool permission prompts, which is why the allow list exists. Treat it like running a script you reviewed.
- Only stdio MCP servers. No OAuth or remote servers yet.

## Tests
```
cd plugins/mcp-tool-chain && python3 -m unittest discover -s tests
```
Uses a fake MCP server (`tests/fake_mcp.py`); no network. The network-isolation test is skipped where user namespaces are blocked.
