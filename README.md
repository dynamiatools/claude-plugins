# Dynamia Tools: Claude Code plugins

The plugins we use every day at [Dynamia](https://dynamiasoluciones.com) to work with [Claude Code](https://claude.com/claude-code), free under MIT. Each plugin is independent: install only the ones you need.

```
/plugin marketplace add dynamiatools/claude-plugins
/plugin install <plugin>@dynamia-tools
```

From a terminal (for example in a Remote Control session, where `/plugin` does not run):

```
claude plugin marketplace add dynamiatools/claude-plugins
claude plugin install <plugin>@dynamia-tools
```

## Plugins

| Plugin | What it is | Install |
|---|---|---|
| [`dynamia`](plugins/dynamia) | Safe, token-cheap work across several repos: batches, worktrees, tests, ship. 19 skills, 4 helper agents, guard hooks, the `ms-workspace` tool and a dev-env panel | `dynamia@dynamia-tools` |
| [`dynamia-craft`](plugins/dynamia-craft) | Working discipline: ask before building, find the root cause before fixing, plan in small steps, answer clearly. 6 skills, no hooks | `dynamia-craft@dynamia-tools` |
| [`dynamia-platform`](plugins/dynamia-platform) | Work on [Dynamia Platform](https://dynamia.tools) projects: backend patterns, ZK, Vue frontend, live docs from GitHub and the `dynamia` CLI. 7 skills, 2 light hooks | `dynamia-platform@dynamia-tools` |
| [`dynamia-ui`](plugins/dynamia-ui) | UI and UX: extract, improve or create a design system; review UX and mobile, SEO, offline, performance; stack advice; a `ds-scan` tool. 8 skills, 1 agent, no hooks | `dynamia-ui@dynamia-tools` |
| [`dynamia-colombia`](plugins/dynamia-colombia) | Colombian tax and compliance: DIAN glossary, electronic invoicing, información exógena, taxes, and citing current rules from official sources. 5 skills, a NIT tool, no hooks | `dynamia-colombia@dynamia-tools` |
| [`dynamia-java`](plugins/dynamia-java) | Modern Java 25 and Spring Boot 4: idioms, concurrency, Spring Boot and Hibernate 7 practices, upgrades, Java review. 6 skills, no hooks | `dynamia-java@dynamia-tools` |
| [`dynamia-kotlin`](plugins/dynamia-kotlin) | Kotlin for backends: idioms, coroutines, Spring Boot 4, Ktor and Exposed, Gradle and Maven, review. 6 skills, no hooks | `dynamia-kotlin@dynamia-tools` |
| [`dynamia-test`](plugins/dynamia-test) | Testing: strategy and review, JUnit 6 and Spring Boot 4, Vitest and Playwright, failing-test triage, coverage and mutation gates. 5 skills, no hooks | `dynamia-test@dynamia-tools` |
| [`dynamia-docs`](plugins/dynamia-docs) | Docs: README and docs layout, ADRs, API docs, changelogs, runbooks, diagrams, docs audits. 7 skills, no hooks | `dynamia-docs@dynamia-tools` |
| [`mcp-tool-chain`](plugins/mcp-tool-chain) | Chain many MCP tool calls in one short Python script so intermediate results stay out of the context; imports the stdio MCP servers it finds. 2 skills, an MCP server, no hooks | `mcp-tool-chain@dynamia-tools` |

Each works on its own; they only point to each other as optional extras, and recommend installing the sibling when it is missing. Together they cover the workflow (`dynamia`), the way of working (`dynamia-craft`), the framework (`dynamia-platform`) and the interface (`dynamia-ui`).

## Repository layout

```
.claude-plugin/marketplace.json   the catalog: one entry per plugin
plugins/<name>/                   one folder per plugin, with its own README, tests, LICENSE and version
CLAUDE.md                         how we create, update and manage plugins here (read it before contributing)
```

## Contributing

Work happens on a branch and goes to `master` through a pull request. The conventions, the checklist for a new plugin and the release steps are in [CLAUDE.md](CLAUDE.md).

## License

[MIT](LICENSE), Copyright (c) 2026 Dynamia Soluciones. A plugin that adapts third-party material says so in its own `NOTICE`.
