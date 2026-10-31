"""repo-map: cheap code lookups through git, so the agent does not read whole files. Read-only."""
import os
import re
from pathlib import Path

from mcplib import Tool, ToolFail, run, serve

ROOT = Path(os.environ.get("DYNAMIA_ROOT", os.getcwd())).resolve()
MAX = 60

# One regex per language family; group "name" is the symbol. Declarations only, no parsing.
PATTERNS = {
    (".java", ".kt", ".groovy"): re.compile(
        r"^\s*(?:(?:public|private|protected|internal|static|final|abstract|open|sealed|data|override|suspend|default|synchronized)\s+)*"
        r"(?:(?P<kind>class|interface|enum|record|object|fun)\s+(?P<name>\w+)|(?:[\w<>\[\],.? ]+\s+)(?P<method>\w+)\s*\([^;]*\)\s*(?:throws [\w., ]+)?\s*\{)"),
    (".py",): re.compile(r"^\s*(?P<kind>class|def|async def)\s+(?P<name>\w+)"),
    (".ts", ".tsx", ".js", ".jsx", ".mjs"): re.compile(
        r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?(?P<kind>class|function|interface|type|enum|const)\s+(?P<name>\w+)"),
    (".go",): re.compile(r"^(?P<kind>func|type)\s+(?:\([^)]*\)\s*)?(?P<name>\w+)"),
}
SKIP_METHOD = {"if", "for", "while", "switch", "catch", "return", "new", "else", "synchronized", "try"}


def inside(path: str) -> Path:
    p = (ROOT / path).resolve()
    if ROOT not in p.parents and p != ROOT:
        raise ToolFail("path is outside the project")
    return p


def git(*argv: str) -> str:
    r = run(["git", *argv], cwd=str(ROOT))
    if r.returncode != 0:
        raise ToolFail(r.stderr.strip() or "git failed")
    return r.stdout


def symbols_of(text: str, suffix: str) -> list[dict]:
    pattern = next((p for exts, p in PATTERNS.items() if suffix in exts), None)
    if pattern is None:
        raise ToolFail(f"no symbol rules for {suffix or 'this file'}")
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        m = pattern.match(line)
        if m is None:
            continue
        name, kind = m.group("name"), m.groupdict().get("kind")
        if name is None:
            name, kind = m.groupdict().get("method"), "method"
        if name and name not in SKIP_METHOD:
            out.append({"line": i, "kind": kind or "symbol", "name": name})
    return out


def symbols(args: dict):
    p = inside(args["file"])
    if not p.is_file():
        raise ToolFail("not a file")
    return symbols_of(p.read_text(errors="replace"), p.suffix)


def callers(args: dict):
    name = args["name"]
    if not re.fullmatch(r"[\w$.]+", name):
        raise ToolFail("name must be an identifier")
    r = run(["git", "grep", "-n", "-w", "-I", "--", name], cwd=str(ROOT))
    hits = [h for h in r.stdout.splitlines() if h]
    rows = []
    for h in hits[:MAX]:
        path, line, text = h.split(":", 2)
        rows.append({"file": path, "line": int(line), "text": text.strip()[:140]})
    return {"total": len(hits), "shown": len(rows), "hits": rows}


def changed_since(args: dict):
    ref = args.get("ref") or "HEAD"
    if not re.fullmatch(r"[\w./~^@-]+", ref) or ref.startswith("-"):
        raise ToolFail("bad ref")
    rows = [dict(zip(("status", "file"), l.split("\t", 1))) for l in git("diff", "--name-status", ref).splitlines()]
    for l in git("ls-files", "--others", "--exclude-standard").splitlines():
        rows.append({"status": "?", "file": l})
    return rows[:200]


def tests_for(args: dict):
    stem = Path(args["file"]).stem
    if re.search(r"(Test|Tests|Spec|IT)$|^test_|\.test$|_test$", stem):
        raise ToolFail("that already looks like a test")
    names = {f"{stem}Test", f"{stem}Tests", f"{stem}Spec", f"{stem}IT", f"test_{stem}", f"{stem}_test", f"{stem}.test", f"{stem}.spec"}
    return [f for f in git("ls-files").splitlines() if Path(f).stem in names or Path(f).name.split(".")[0] in names][:20]


TOOLS = {
    "symbols": Tool("Classes, functions and methods declared in a file, with line numbers (java, kotlin, groovy, python, ts/js, go).",
                    {"file": {"type": "string"}}, symbols, ("file",)),
    "callers": Tool("Where a name appears in the tracked files (whole-word match, first 60), with the line text.",
                    {"name": {"type": "string"}}, callers, ("name",)),
    "changed_since": Tool("Files changed against a ref (default HEAD), plus untracked ones, with status letters.",
                          {"ref": {"type": "string"}}, changed_since),
    "tests_for": Tool("Test files that match a source file by name (FooTest, test_foo, foo.test.ts ...).",
                      {"file": {"type": "string"}}, tests_for, ("file",)),
}

if __name__ == "__main__":
    serve("repo-map", TOOLS)
