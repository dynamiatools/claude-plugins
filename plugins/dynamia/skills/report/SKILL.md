---
name: report
description: Shows how work and plan usage are going, with current 5h and weekly usage and pace, where tokens went in recent sessions, and what the action log says (slow or flaky tests, cost per batch). Use when the user asks how it is going, whether tokens are being burned, whether there is enough budget to finish something, or what to optimize. Triggers on "cómo voy de uso del plan", "estoy gastando muchos tokens".
argument-hint: "[days]"
allowed-tools: Bash(ms-workspace usage:*) Bash(ms-workspace insights:*) Bash(ms-workspace tokens:*) Bash(ms-workspace budget:*) Bash(ms-workspace memory:*)
---

# dynamia:report

A short, decision-oriented report built from three deterministic commands. Do not read raw logs or transcripts yourself.

## Steps

1. **Collect** (`$ARGUMENTS` is an optional number of days; omit `--days` when it is empty):
   ```bash
   ms-workspace usage
   ms-workspace insights --days $ARGUMENTS
   ms-workspace tokens --days $ARGUMENTS
   ms-workspace budget
   ```
   If a command says there is no data (no status line snapshot, no workspace, no sessions), say what is missing and how to enable it (`/dynamia:setup`), then continue with what exists.

2. **Answer in at most 12 lines**, in this order:
   - **Budget**: used and left in the 5h window and the week, time to reset, verdict. If the user mentions a task, check it with `ms-workspace usage --check --need <pct or auto>` and say plainly whether it fits.
   - **Baseline**: what every session loads before any work (`budget`) and its biggest item, only if it is large.
   - **Burn**: what dominates the token use (batch or repo, tool results, repeated reads) and the one or two hints the audit printed.
   - **Quality**: flaky candidates, slowest runs, conflicts or ship failures, only if non-zero.
   - **Next step**: one concrete action (for example "finish batch X before starting another", "narrow Bash output with rtk", "pause until the window resets at HH:MM").

3. If the verdict is WARN or CRITICAL and work is in progress, offer to leave a handoff note: `ms-workspace memory add --type handoff --batch <batch> "state, next step, files touched"`.

## Notes
- Token figures from tool results are approximations (characters divided by 4).
- Batch cost is approximate: usage jumps between logged events of the batch, so parallel work elsewhere is counted too.
