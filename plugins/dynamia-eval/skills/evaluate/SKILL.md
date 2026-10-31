---
name: evaluate
description: Checks a prompt, message, diff or any text against the project's local rules and says which pass and which fail. Deterministic rules run in a script, the rest are judged in one pass. Use when the user asks to evaluate, check, grade or validate something against rules.
---

# dynamia-eval:evaluate

Details of the rules and the script are in `${CLAUDE_PLUGIN_ROOT}/REFERENCE.md`. Read it only if something below is unclear.

1. **Rules.** Use `.dynamia-eval/rules/` of the project. If it does not exist, say so and offer `/dynamia-eval:draft` (build rules from a conversation) or the samples in `${CLAUDE_PLUGIN_ROOT}/examples/rules`. Do not invent rules.
2. **State.** The text to evaluate: what the user pasted, named, or the last message if they said "this". For long or multi-line text write it to a file in the scratchpad and pass `--state-file`.
3. **Check.** `python3 ${CLAUDE_PLUGIN_ROOT}/bin/eval.py check --rules <dir> --state-file <file>`. Exit 2 means bad rules: show the errors and stop.
4. **Judge the `pending` rules, all in one pass.** Answer each from the state and that rule's `instructions` and `criteria` only. Write one JSON object `{"<id>": <answer>, ...}` in the shape of `answer_format` to a scratchpad file. Give the probability you really hold, not 0 or 1 by habit; when the state does not contain what the criteria need, say a middle value and add it to your report.
5. **Verdict.** Save the `check` output to a file and run `eval.py verdict --checked <that file> --answers <answers file>`. If nothing is pending, the `check` output already has every verdict and this step is not needed.
6. **Report** in a few lines: the overall result, then only the rules that failed, were warned or are incomplete, each with its detail and one concrete fix. List the passing ones as a single line of ids.

Say plainly that judged answers are the model's estimate, not a calibrated probability. Never report a pass for a rule that has no valid answer.
