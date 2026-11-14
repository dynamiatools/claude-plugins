---
name: contract
description: Looks up the real declaration (field names and types) of a DTO or type in the workspace repos with ms-workspace contract, so an API is mapped from the code that serves it and not from docs or memory. Use before writing or reviewing a client, mapper or request body against another repo's API.
argument-hint: "<TypeName> [--repo R]"
allowed-tools: Bash(ms-workspace contract:*)
---

# dynamia:contract

Docs and issue text drift; the DTO in the code that serves the API does not. Before you map a payload, read the real declaration.

## Steps

1. `ms-workspace contract <TypeName>`: prints each declaration of that exact name (Kotlin `data class`, Java `class`/`record`/`interface`, Groovy, TypeScript `interface`/`type`) with its file and line across every repo of the workspace. `--repo R` narrows it, `--max-lines N` raises the cap (default 80).
2. Not found: it lists similar names; pick the right one and run it again. Names are case-sensitive for the exact match.
3. **Check which API serves it.** Two endpoints can look alike and take different DTOs (for example a web-app API versus the public `/api/v2`). Open the controller that references the type (`grep -rn <TypeName>` in that repo) and confirm the route before you rely on the fields.
4. Use the field names exactly as declared, and note nullable and numeric types (`Double` on the wire is not a decimal string).

## Notes
- Read-only and fast; it skips `node_modules`, `target`, `build`, `dist` and similar folders.
- It shows declarations, not behavior: validation and pricing rules live in the services, read them when the task depends on them.
