# dynamia-platform

Claude Code plugin for projects built on [Dynamia Platform](https://dynamia.tools) (DynamiaTools): Java 25, Spring Boot, ZK, view descriptors in YAML and the `@dynamia-tools` Vue/TypeScript packages. It works on its own; it does not need any other plugin.

```
/plugin marketplace add dynamiatools/claude-plugins
/plugin install dynamia-platform@dynamia-tools
```

## What you get

| Skill | Use it to |
|---|---|
| `dynamia-platform:backend` | Write entities, `CrudService` code, `ModuleProvider`/`CrudPage`, actions (also headless/stateless ones for REST clients), validators, listeners and YAML view descriptors. References: `CrudService`/`QueryParameters`/`QueryConditions`, `EntityHandler`/`DomainUtils`, configuration properties, view descriptors, testing, security and sessions, `Containers`/`ObjectsContext`, loading collections without OSIV, `BeanMap` auto-DTOs, `QueryBuilder`, module conventions, utilities and `SchedulerUtil`, navigation scope and app metadata, SaaS multi-tenancy (`@TenantId`, `AccountTenants`, root tenant) |
| `dynamia-platform:zk-ui` | Work on ZUL pages, MVVM view models, `CrudController`, test view models, embed Vue bundles with `<microfrontend>` |
| `dynamia-platform:vue-frontend` | Use `@dynamia-tools/sdk`, `ui-core`, `vue` and the extension SDKs; choose between Vue, ZK and both |
| `dynamia-platform:dates` | Migrate legacy `java.util.Date` code to `java.time` with `DateTimeUtils`, `LocalDateRange` and `QueryConditions` |
| `dynamia-platform:extensions` | Use the framework extensions: entity-files (local, S3, Buckie), reports, http-functions (versioned third-party calls), finances (taxes, totals, money), dashboard, email-sms, file-importer and saas |
| `dynamia-platform:docs` | Read the official docs and package READMEs live from GitHub, at the tag of the project's version |
| `dynamia-platform:cli` | Check, install or auto-update the `dynamia` CLI (`bin/dp-cli-update`) and create a project with `dynamia new` (flags only, never the interactive wizard) |

## Hooks

| Hook | What it does |
|---|---|
| SessionStart | `bin/dp-detect` prints one line (stack, ZK/Vue, version) only inside a Dynamia project. Silent elsewhere. |
| PreToolUse (Bash) | Blocks `dynamia new` when flags are missing, because the wizard would hang the session. Everything else passes. |

Both are POSIX `sh` with no dependencies (Linux, macOS), never fail the session, and the guard blocks only an unmistakable `dynamia new`.

## Tools

`bin/dp-cli-update [--apply]` compares the installed CLI with the latest on npm (`status=current|outdated|missing|unknown`); with `--apply` it updates it. It never uses `sudo`: a global npm folder outside `$HOME` that is not writable stops with a message.

`bin/dp-detect [dir]` prints the summary; `--facts` prints `key=value` lines (backend, zk, vue, sdk, microfrontend, descriptors, version, cli, node, java).

## Tests

```
python3 -m unittest discover -s tests
```

## Credits and license

MIT. Skills adapt the `dynamia-tools` skill and package READMEs of [dynamiatools/framework](https://github.com/dynamiatools/framework), Apache-2.0; see `NOTICE`.
