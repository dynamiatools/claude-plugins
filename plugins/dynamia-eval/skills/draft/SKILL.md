---
name: draft
description: Drafts the evaluation rules from a conversation, a spec or a text, extracting the criteria, decisions and rejections into rules with examples, and writes them only after the user approves. Use when the user wants to turn what was just discussed into rules.
---

# dynamia-eval:draft

Rule schema: `${CLAUDE_PLUGIN_ROOT}/REFERENCE.md`. Source: this conversation, unless the user gives a file or pasted text. If the conversation is not in your context, ask for the text; do not guess.

1. **Extract criteria.** Read for what the user wants to hold: explicit requirements, things they corrected or rejected, "always" and "never". Skip one-off details and anything that is a preference of the moment. Quote the short phrase each criterion came from.
2. **Choose the cheapest form.** A pattern, a length or a forbidden word is a `check` rule. Only what needs reading comprehension is judged. Split a criterion that mixes two things. Do not write a rule you cannot give a `pass` and a `fail` example for.
3. **Ask about doubtful ones.** If a criterion is vague, ask one short question per doubt instead of inventing a threshold. Make `severity = "block"` only for what the user called a must.
4. **Write the draft in your reply, not on disk yet**, as a table: id, type, check or judged, severity, source quote. Mention any overlap with existing rules in `.dynamia-eval/rules/`.
5. **Wait for approval** per rule or for the whole set. Then write the files (one topic per file) and run `validate` and `selftest` as in `/dynamia-eval:rules`. Fix what fails and report it; do not ship a rule whose examples fail.
6. **Report**: rules written, which are judged, and anything you left out and why.

Not verified by this skill: whether the extracted criteria are the ones the user really cares about. Say that the first evaluations are the real test.
