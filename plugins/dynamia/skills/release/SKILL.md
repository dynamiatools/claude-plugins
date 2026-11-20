---
name: release
description: Shows what waits to be promoted from a base branch to qa or main, and drafts release notes, with ms-workspace release. Read-only. Use when the user asks what is pending for a release, what changed since qa or main, or for release notes. Triggers on "qué falta para pasar a qa", "notas de la release".
argument-hint: "status | notes [repo]"
---

# dynamia:release

```bash
ms-workspace release status [repo]   # commits waiting, by type, authors, diffstat, breaking changes, hotfix drift
ms-workspace release notes [repo]    # markdown grouped by commit type
```

## Steps
1. Run `status`; summarize per repo in a few lines (for a long list hand the output to `dynamia:summarizer`, at most 10 lines, and check its breaking-change and hotfix-drift lines against the output yourself) and call out breaking changes and hotfix drift (commits only on `qa`/`main`).
2. Run `notes` only when asked; print the markdown as is.
3. This only reads. Promoting to `qa`/`main` is done by the user.
