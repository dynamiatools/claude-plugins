---
name: rules
description: Lists, validates, adds, edits and removes the project's evaluation rules in .dynamia-eval/rules, and tests them with their examples. Use when the user wants to see, write or change a rule, or to check that the rules are valid and distinguish good from bad.
---

# dynamia-eval:rules

Schema, rule types and script commands: `${CLAUDE_PLUGIN_ROOT}/REFERENCE.md`. Read it before writing a rule.

- **List**: read the files in `.dynamia-eval/rules/` and show one line per rule: id, type, severity, `check` or judged. Run `validate` and show its errors, if any.
- **Add or edit**: ask only what is missing (what must hold, how bad a miss is). Prefer a deterministic `check` when a pattern or length decides it; use a judged rule only when it needs reading comprehension. Write `instructions` as a question about one thing, and `criteria` with the edge cases. Add at least one `pass` and one `fail` example. Keep the file readable: one topic per file.
- **Always after a change**: `python3 ${CLAUDE_PLUGIN_ROOT}/bin/eval.py validate --rules .dynamia-eval/rules`, then `selftest` (see below). Fix the rule, not the example, unless the example is wrong.
- **Selftest**: run `selftest`. For `pending` entries answer each from its `state`, `instructions` and `criteria` only (they come without the expected result on purpose), save `{"<key>": <answer>}` to a file and run `selftest --answers <file>`. A failing example means the rule is vague: rewrite its criteria.
- **Remove**: show the rule and confirm before deleting it.

Ask before creating `.dynamia-eval/` in a project. Never put secrets in a rule or an example.
