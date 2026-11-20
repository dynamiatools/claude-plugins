---
name: memory
description: Saves, lists, searches, shows and forgets the workspace's durable notes (decisions, lessons, gotchas, handoffs) with ms-workspace memory. Use when the user asks to remember something, note a decision or lesson, leave a handoff, or see what was noted before. Triggers on "recuerda que...", "anota esta decisión".
argument-hint: "add <text> | list | search <words> | show <name> | forget <name>"
---

# dynamia:memory

One markdown note per durable fact in `<workspace>/memory/`. It is the source of truth; `recall.db` is only a search index over it.

```bash
ms-workspace memory add --type decision|lesson|gotcha|handoff [--batch B] [--title T] "<text>"
ms-workspace memory list [--type T] [--batch B] [-n N]
ms-workspace memory search <words...>
ms-workspace memory show <name>
ms-workspace memory forget <name>
```

## Steps
1. **Save** when the user asks to remember something, or when a decision, a gotcha or a lesson came up that the next session would otherwise lose. Write the why, not just the what, in one to three lines. Pick the type: `decision` (we chose X because Y), `gotcha` (this breaks when Z), `lesson` (what worked or failed), `handoff` (state, next step and files touched, with `--batch`).
2. **Never save** secrets, tokens, or what the code or git history already shows.
3. **Before adding**, run `memory search` on two key words; if a note covers it, say so instead of duplicating it.
4. **Find**: `search` for exact words; for older sessions or the log use `/dynamia:recall`.
5. **Forget** only the note the user names, after showing it with `show`.
6. If you must stop before finishing (usage critical, interrupted), leave a `handoff` for the batch before ending.

## Notes
- Handoffs disappear with their batch. Other notes stay.
- Nothing is written automatically except the hook-made auto handoff, which needs the hooks from `/dynamia:setup`.
