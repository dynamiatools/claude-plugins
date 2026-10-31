"""board: a list of issues the agent is working on, kept per repo in a file, readable and writable in one call.

It is its own list. It does not read or write the pane of any other plugin.
"""
import json
import os
import re
import time
from pathlib import Path

from mcplib import Tool, ToolFail, run, serve

STATES = ("work", "pr", "done")
KEEP = 50


def state_dir() -> Path:
    base = os.environ.get("DYNAMIA_STATE") or os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "dynamia-mcp")
    return Path(base) / "board"


def repo_key() -> str:
    r = run(["git", "remote", "get-url", "origin"], cwd=os.environ.get("DYNAMIA_ROOT") or os.getcwd())
    m = re.search(r"github\.com[:/]([^/\s]+/[^/\s]+?)(?:\.git)?/?$", r.stdout.strip()) if r.returncode == 0 else None
    if m is None:
        raise ToolFail("no GitHub remote named origin here")
    return m.group(1).replace("/", "__")


def path() -> Path:
    return state_dir() / f"{repo_key()}.json"


def load() -> list[dict]:
    try:
        return json.loads(path().read_text())
    except FileNotFoundError:
        return []


def save(items: list[dict]) -> None:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(items[-KEEP:], ensure_ascii=False))
    tmp.replace(p)


def board_list(args: dict):
    items = load()
    state = args.get("state")
    return [i for i in items if state is None or i["state"] == state]


def board_set(args: dict):
    items = {i["n"]: i for i in load()}
    changed = []
    for c in args["updates"]:
        n, state = c.get("n"), c.get("state")
        if not isinstance(n, int) or state not in (*STATES, "drop"):
            raise ToolFail(f"bad update {c}: n is an integer, state one of {', '.join((*STATES, 'drop'))}")
        if state == "drop":
            items.pop(n, None)
        else:
            old = items.get(n, {})
            items[n] = {"n": n, "state": state, "title": c.get("title") or old.get("title", ""), "at": int(time.time())}
        changed.append(f"#{n} {state}")
    save(list(items.values()))
    return {"changed": changed, "total": len(items)}


def board_clear(_: dict):
    save([])
    return {"cleared": True}


TOOLS = {
    "list": Tool("The tracked issues of this repo, newest last: {n, state, title, at}. Optional state filter (work, pr, done).",
                 {"state": {"type": "string", "enum": list(STATES)}}, board_list),
    "set": Tool("Set the state of issues in one call: work, pr, done, or drop to remove. Title is optional.",
                {"updates": {"type": "array", "items": {"type": "object", "properties": {
                    "n": {"type": "integer"}, "state": {"type": "string", "enum": [*STATES, "drop"]}, "title": {"type": "string"}},
                    "required": ["n", "state"]}}}, board_set, ("updates",), read_only=False),
    "clear": Tool("Empty the list of this repo.", {}, board_clear, read_only=False),
}

if __name__ == "__main__":
    serve("board", TOOLS)
