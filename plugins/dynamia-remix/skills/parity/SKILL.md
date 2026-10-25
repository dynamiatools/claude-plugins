---
name: parity
description: Scores how much of the original the remix does, weighted by must, should and could, and lists what is missing in build order, with remix-parity. Use when the user asks how close the remix is, what is missing, or whether it is ready, and after /dynamia-remix:build.
---

# parity

Parity means it does the same job, not that it looks the same. Do not chase pixel parity: the original's exact look is its trade dress, and `/dynamia-remix:brand` changes it on purpose.

1. Make `remix/features.csv` current. Every `clone` value is `yes`, `partial` (with a note), `no`, or `skip` (with a reason). Rows the original does not have go in with `original=no`.
2. Run:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/bin/remix-parity remix/features.csv
python3 ${CLAUDE_PLUGIN_ROOT}/bin/remix-parity remix/features.csv --markdown > remix/parity.md
```

It weights must 3, should 2, could 1, counts partial as half, leaves out `skip` rows and your additions, and prints the score, must-haves done, areas weakest first and the missing list in build order. Exit 1 when a must-have is not done (not shippable) or under `--fail-under N`.

3. Report the score and the missing list. Do not round a partial up to done, and do not mark `yes` what you did not check in the running app.

Next: `/dynamia-remix:voice` to decide what to improve beyond parity.
