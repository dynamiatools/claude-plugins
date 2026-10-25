"""A tiny stdio MCP server for the tests: add (read-only), echo (read-only), delete (write), boom (fails)."""
import json
import sys

TOOLS = [
    {"name": "add", "description": "Add two numbers.", "annotations": {"readOnlyHint": True},
     "inputSchema": {"type": "object", "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
                     "required": ["a", "b"]}},
    {"name": "echo-text", "description": "Echo text back.", "annotations": {"readOnlyHint": True},
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
    {"name": "delete", "description": "Delete an item.",
     "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}},
    {"name": "boom", "description": "Always fails.", "annotations": {"readOnlyHint": True},
     "inputSchema": {"type": "object", "properties": {}}},
]


def text(s, error=False):
    return {"content": [{"type": "text", "text": s}], "isError": error}


for line in sys.stdin:
    msg = json.loads(line)
    if "id" not in msg:
        continue
    method, args = msg["method"], msg.get("params", {}).get("arguments", {})
    if method == "initialize":
        result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                  "serverInfo": {"name": "fake", "version": "0"}}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    else:
        name = msg["params"]["name"]
        if name == "add":
            result = {"content": [], "structuredContent": {"sum": args["a"] + args["b"]}}
        elif name == "echo-text":
            result = text(args["text"])
        elif name == "delete":
            result = text(json.dumps({"deleted": args["id"]}))
        else:
            result = text("it broke", error=True)
    print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}), flush=True)
