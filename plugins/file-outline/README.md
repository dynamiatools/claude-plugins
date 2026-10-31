# file-outline

A side pane with the outline of the text file the agent last read, edited or wrote: headings, classes, functions, sections. A mod: no skills, no agents.

- The pane opens by itself when the agent touches a file that has an outline, and follows the next one. Each entry shows its line number, indented by depth.
- `/outline <path>` shows the outline of any file (relative to the shell's folder).

| Files | Listed |
|---|---|
| Markdown (`.md`, `.mdx`) | `#` headings, outside fenced code |
| YAML | top-level keys (and the ones indented once) |
| TOML | `[sections]` |
| ts, js, py, java, kt, go, rs, sh, php, rb, swift, cs, scala | classes, interfaces, functions, methods |

## Install
```
/plugin install file-outline@dynamia-tools
```

## Limits
- Line patterns, not a parser: a method without a keyword (`save() {}` in a JS class) or a signature split over lines is not listed.
- Files over 1 MB, binary files and kinds with no outline are skipped.
- The pane needs a wide terminal; below that it waits undrawn.
- Not yet verified in a live session; see the PR.

## Tests
```
claude plugin test plugins/file-outline
```
