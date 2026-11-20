---
name: recall
description: Full-text search over past Claude Code sessions, memory notes and the action log with ms-workspace recall. Read-only. Use when the user asks where something was decided, what was tried before, or to find an earlier conversation. Triggers on "dónde decidimos esto", "busca en las sesiones anteriores".
argument-hint: "<words...> [--kind K] [-n N]"
---

# dynamia:recall

```bash
ms-workspace recall <words...> [--kind K] [-n N]
```

## Steps
1. Turn the question into 2-4 distinctive words (names, error text), not a sentence.
2. Run it and show the best hits: date, kind, one line. Results point to `claude --resume <id>` for the full session.
3. No hits: try one synonym or a narrower `--kind`, then say nothing was found. Do not invent a decision.
4. Offer `ms-workspace memory add --type decision "..."` when the answer is worth keeping.
