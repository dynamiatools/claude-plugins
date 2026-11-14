"""ms-workspace contract <Name>: show the declaration of a DTO or type across the repos of the workspace.

    ms-workspace contract SaleDTO [--repo R] [--max-lines N]

Looks for `data class`, `class`, `record`, `interface`, `enum` and TypeScript `type` declarations of that exact name in every
repo's sources (Kotlin, Java, Groovy, TypeScript) and prints the file, the line and the declaration (the constructor
parameters of a Kotlin data class, or the body for a Java record, class or TypeScript interface). When the name is not found it
lists declarations that contain it. Read-only and fast enough for a large ERP: it prunes build and dependency folders.

Use it before mapping an API: it answers "what are the real field names of this DTO?" from the code that serves it."""
from __future__ import annotations

import os
import re
from pathlib import Path

from .core import Workspace, die

EXTENSIONS = (".kt", ".java", ".groovy", ".ts", ".tsx")
PRUNE = {".git", "node_modules", "target", "build", "dist", ".gradle", ".idea", ".nuxt", ".output", ".dynamia", "working-trees", ".batches", "out"}
KINDS = r"(?:data\s+class|enum\s+class|sealed\s+class|abstract\s+class|class|record|interface|enum|object|typealias|type)"
DEFAULT_MAX = 80
CANDIDATES = 12


def declaration(pattern: re.Pattern, text_lines: list[str], start: int, max_lines: int) -> list[str]:
    """The declaration starting at line `start`: up to the closing bracket of the first opening one ( ( [ { ), capped."""
    out, depth, opened, closer = [], 0, "", ""
    pairs = {"(": ")", "{": "}", "[": "]"}
    for n in range(start, min(len(text_lines), start + max_lines)):
        line = text_lines[n]
        out.append(line.rstrip())
        for ch in line:
            if not opened and ch in pairs:
                opened, closer, depth = ch, pairs[ch], 1
            elif opened and ch == opened:
                depth += 1
            elif opened and ch == closer:
                depth -= 1
                if depth == 0:
                    return out
        if not opened and (line.rstrip().endswith(";") or n > start + 3):
            return out   # a type alias or a one-line declaration
    return out + [f"... (cut at {max_lines} lines)"]


def search(roots: list[tuple[str, Path]], name: str, max_lines: int) -> tuple[list[str], list[str]]:
    exact = re.compile(rf"\b{KINDS}\s+{re.escape(name)}\b")
    loose = re.compile(rf"\b{KINDS}\s+(\w*{re.escape(name)}\w*)", re.I)
    hits, near = [], []
    for repo, root in roots:
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in PRUNE]
            for f in files:
                if not f.endswith(EXTENSIONS):
                    continue
                path = Path(dirpath) / f
                try:
                    lines = path.read_text(errors="replace").splitlines()
                except OSError:
                    continue
                for i, line in enumerate(lines):
                    if re.match(r"\s*(import|export\s*\{|//|\*|/\*)", line):
                        continue   # `import type X from ...` and comments are not declarations
                    if exact.search(line):
                        rel = path.relative_to(root)
                        hits.append(f"{repo}/{rel}:{i + 1}\n" + "\n".join(declaration(exact, lines, i, max_lines)))
                    elif len(near) < CANDIDATES and (m := loose.search(line)):
                        near.append(f"{repo}/{path.relative_to(root)}:{i + 1}  {m.group(0)}")
    return hits, near


def cmd_contract(ws: Workspace | None, args: list[str]) -> int:
    if ws is None:
        die("contract needs a workspace (run the dynamia:workspace-init skill first)")
    only, max_lines, names, it = "", DEFAULT_MAX, [], iter(args)
    for a in it:
        if a in ("--repo", "--max-lines"):
            v = next(it, None)
            if v is None:
                die(f"contract: {a} needs a value")
            if a == "--repo":
                only = v
            elif v.isdigit() and int(v) > 0:
                max_lines = int(v)
            else:
                die("contract: --max-lines is a positive number")
        elif a.startswith("-"):
            die(f"contract: unknown option {a}")
        else:
            names.append(a)
    if len(names) != 1 or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", names[0]):
        die("usage: contract <TypeName> [--repo R] [--max-lines N]")
    repos = [r for r in ws.repo_names() if not only or r == only]
    if only and not repos:
        die(f"contract: unknown repo '{only}'")
    roots = [(r, ws.repo_dir(r)) for r in repos if ws.repo_dir(r).is_dir()]
    hits, near = search(roots, names[0], max_lines)
    if hits:
        print("\n\n".join(hits))
        return 0
    print(f"no declaration named {names[0]} in {', '.join(r for r, _ in roots) or 'any repo'}")
    if near:
        print("similar names:")
        print("\n".join("  " + n for n in near))
    return 1
