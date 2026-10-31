"""A tiny stdio MCP server loop (newline-delimited JSON-RPC), standard library only.

A server is a dict of tools: name -> Tool(description, properties, required, read_only, fn).
fn(args) returns any JSON value; raising ToolFail reports an error to the caller.
"""
import json
import subprocess
import sys
from dataclasses import dataclass
from typing import Any, Callable


class ToolFail(Exception):
    pass


@dataclass
class Tool:
    description: str
    properties: dict
    fn: Callable[[dict], Any]
    required: tuple = ()
    read_only: bool = True


def run(argv: list[str], cwd: str | None = None, timeout: int = 60) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise ToolFail(f"{argv[0]} is not installed")
    except subprocess.TimeoutExpired:
        raise ToolFail(f"{' '.join(argv[:3])} timed out after {timeout}s")


def listing(tools: dict[str, Tool]) -> list[dict]:
    return [
        {
            "name": name,
            "description": t.description,
            "annotations": {"readOnlyHint": t.read_only},
            "inputSchema": {"type": "object", "properties": t.properties, "required": list(t.required)},
        }
        for name, t in tools.items()
    ]


def call(tools: dict[str, Tool], name: str, args: dict) -> dict:
    tool = tools.get(name)
    if tool is None:
        return {"content": [{"type": "text", "text": f"unknown tool {name}"}], "isError": True}
    missing = [k for k in tool.required if k not in args]
    if missing:
        return {"content": [{"type": "text", "text": f"missing: {', '.join(missing)}"}], "isError": True}
    try:
        value = tool.fn(args)
    except ToolFail as e:
        return {"content": [{"type": "text", "text": str(e)}], "isError": True}
    out = {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}]}
    # structuredContent must be an object; a list or scalar goes as text only, which clients parse as JSON.
    if isinstance(value, dict):
        out["structuredContent"] = value

    return out


def serve(server_name: str, tools: dict[str, Tool]) -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        msg = json.loads(line)
        if "id" not in msg:
            continue
        method, params = msg.get("method"), msg.get("params") or {}
        if method == "initialize":
            result = {
                "protocolVersion": params.get("protocolVersion", "2025-06-18"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": server_name, "version": "0.1.0"},
            }
        elif method == "tools/list":
            result = {"tools": listing(tools)}
        elif method == "tools/call":
            result = call(tools, params.get("name", ""), params.get("arguments") or {})
        elif method == "ping":
            result = {}
        else:
            print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": f"no {method}"}}), flush=True)
            continue
        print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}), flush=True)
