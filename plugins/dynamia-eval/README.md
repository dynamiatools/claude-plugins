# dynamia-eval

Check any text against rules you keep in the project, locally and fast. Inspired by structured evaluators such as [Cloudflare's `typesafe/jev`](https://developers.cloudflare.com/ai/models/typesafe/jev/): typed questions (`noul`, `choice`, `score`) in, a verdict per rule out. It takes the contract, not the model: there is no calibrated model here.

- **Deterministic first.** A rule with a `check` (regex, length) is resolved by a Python script in milliseconds. If every rule is deterministic, no model is involved.
- **One judging pass for the rest.** The remaining questions are answered by Claude in the same turn, all together, and the script applies each rule's thresholds. Judged answers are the model's estimate, not calibrated probabilities.
- **Rules written for you.** `draft` turns a conversation into rules with examples, and `selftest` proves each rule tells good from bad before it is kept.

| Skill | Use it to |
|---|---|
| `evaluate` | Check a text, prompt or diff against the rules |
| `rules` | List, add, edit, validate and self-test rules |
| `draft` | Build the rules from a conversation or a spec |

No hooks, no MCP server, no network. Python 3.11+ and nothing else. Rules and the script: [REFERENCE.md](REFERENCE.md). Samples: `examples/rules/`.

```
/plugin marketplace add dynamiatools/claude-plugins
/plugin install dynamia-eval@dynamia-tools
```

Tests: `cd plugins/dynamia-eval && python3 -m unittest discover -s tests`.
