---
name: extensions
description: Dynamia Platform extensions from dynamiatools/framework - entity-files, reports (stored queries, REST, export), http-functions (versioned third-party calls), finances (totals, taxes, money), dashboard, email-sms, file-importer, saas. Use when a task attaches or stores files, builds or runs reports, calls an external HTTP API, or calculates invoices, taxes, discounts or withholdings in a Dynamia project.
---

# dynamia-platform:extensions

Extensions are separate modules with their own Maven coordinates, under `extensions/<name>` in `dynamiatools/framework`. Each has a `core` module (domain, services, REST, no ZK) and often a `ui` module (the ZK front end); the Vue side is in `extensions/*/packages` (`@dynamia-tools/*-sdk`, `*-vue`).

1. Confirm the extension is a dependency of the project (`dp-detect --facts`, the `pom.xml`) and which versions. **Coordinates and versions in the extension READMEs are often stale**: check the project's own `pom.xml`, or the framework's.
2. Read the reference for the extension, then verify signatures in the project's sources or `dynamia-platform:docs`.
3. A new feature that is not covered by a reference: read the extension's `README.md` and `core` module first.

| Extension | Use it for | Reference |
|---|---|---|
| `entity-files` | Attach files to any entity, file explorer, local, S3 or Buckie storage, upload/download REST | `references/entity-files.md` |
| `reports` | Reports stored as queries with filters, run and export (XLSX, CSV, PDF), REST, dashboard widget, designer | `references/reports.md` |
| `http-functions` | Call third-party HTTP APIs by name, versioned, configured in the database | `references/http-functions.md` |
| `finances` | Invoices and documents: lines, taxes, discounts, withholdings, totals, money and currency | `references/finances.md` |
| `saas` | Accounts, plans, payments, subdomains, remote status check, tenant export/import/clone | `references/saas.md`; tenants and isolation in `dynamia-platform:backend` `references/saas-tenancy.md` |
| `security` | Users, profiles, access tokens, JWT, sessions, login hooks | `dynamia-platform:backend` `references/security-sessions.md` |
| `dashboard` | Dashboards with widgets for ZK and JS front ends | `references/dashboard.md` |
| `email-sms` | Email and SMS accounts, templates, async sending | `references/email-sms.md` |
| `file-importer` | Excel import with progress and stop | `references/file-importer.md` |

## Rules for all of them
- Most extensions are tenant-aware through the SaaS base entities (`entity-files` is not annotated with `@TenantId`; it carries its own `accountId`). Code that runs outside a request (jobs, startup) needs an explicit tenant (`saas-tenancy.md`).
- Their REST lives under `/apps/api/...` (own front ends) or `/api/...` (integrations), see `navigation-metadata.md`; secure each prefix in the host app.
- Add the module, then its `ModuleProvider` pages appear on their own (some contribute to the `saas` or `system` module).
- Prefer the extension's service or facade over its tables. Do not write SQL against `mod_*` tables.
- Do not copy an extension's README example blindly: verify the signature (they drift).
