# dynamia-eval reference

Rules live in `.dynamia-eval/rules/*.toml` of the project (override with `--rules`). Each file holds `[[rule]]` tables. Ids are unique across files.

```toml
[[rule]]
id = "no-aws-key"            # lowercase letters, digits, - and _
type = "noul"                # noul = true/false, choice = one option, score = an ordered level
severity = "block"           # block (default) fails the evaluation; warn is only reported
source = "quote of the conversation this came from"   # optional
instructions = "..."         # the question for the judge (required unless check is set)
criteria = "..."             # how to decide, with the edge cases
check = { regex = "AKIA[0-9A-Z]{16}", expect = "absent" }   # deterministic, noul only
example = [ { state = "...", expect = "pass" }, { state = "...", expect = "fail" } ]
```

| Type | Extra keys | `pass` | Judge answer |
|---|---|---|---|
| `noul` | none | `min` and/or `max`, numbers 0..1 (default `min = 0.5`) | `{"noul": 0.9}` probability the statement is true |
| `choice` | `options` (2+) | `accept` (subset of options), optional `min_confidence` | `{"choice": "bug", "confidence": 0.8}` |
| `score` | `levels` (2+, lowest first) | `min` and/or `max`, integers 1..len(levels) | `{"score": 2, "confidence": 0.7}` |

`check` keys (all must hold): `regex` with `expect = "present" | "absent"` (and `ignore_case`), `min_chars`, `max_chars`. A rule with `check` is resolved by the script and takes no `pass`.

## Script (`${CLAUDE_PLUGIN_ROOT}/bin/eval.py`, Python 3.11+, standard library)

| Command | Does | Output |
|---|---|---|
| `validate --rules P` | checks the rule files | `{"rules": n, "errors": []}` |
| `check --rules P --state TEXT` (or `--state-file F`, `--state -`) | resolves deterministic rules | `{"resolved": [...], "pending": [...], "answer_format": ...}` |
| `verdict --checked F --answers F` | applies thresholds to the judge's answers | `{"overall", "verdicts", "failed", "warned"}` |
| `selftest --rules P [--answers F]` | runs each rule's `example`s; judged ones come back as `pending` without `expect` | `{"ok", "failed", "pending"}` |

Exit codes: 0 pass, 1 fail, 2 bad rules or usage, 3 incomplete (answers missing or invalid). A judged rule with no valid answer is never a pass.
