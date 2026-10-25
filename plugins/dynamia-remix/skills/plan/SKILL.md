---
name: plan
description: Plans the stack, database schema, API and build order for a remix, from remix/recon.md. Boring managed tech, real SQL with constraints, routes by flow, thin vertical slice first. Use after /dynamia-remix:recon, or when the user asks which stack, schema or API to use for their version of an app.
---

# plan

Reads `remix/recon.md` and `remix/features.csv`; writes `remix/plan.md` and the schema (`remix/schema.sql` or the first migration). No recon map: stop and run `/dynamia-remix:recon`. Planning from memory misses half the app.

## Steps

1. **Stack.** Keep the user's stack if they have one. Otherwise pick boring and managed: one web framework, one Postgres, a hosted auth, Stripe for payments, one email provider. One line of why per choice. One database, no microservices: the remix needs the original's features, not its architecture.
2. **Schema.** Turn the inferred data model into SQL. Every table has an id and timestamps; an owner column on everything a user owns; foreign keys with a decided `on delete`; indexes on foreign keys and filtered columns; check constraints for statuses; `timestamptz` in UTC; money as integer cents plus currency; access rules written down (row level security or one authorisation check per query). Constraints the recon found belong in the database: two guests booking one slot is a unique or exclusion constraint, not a UI check.
3. **API.** One row per route or action: `method path | does | who can call | input | output | flow`. Add webhooks and scheduled jobs. Official public APIs with the user's own keys only, never the original's private endpoints.
4. **Parts that bite.** One line on each that applies: time zones, idempotent webhooks, race conditions, rate limits, search, realtime, offline, email deliverability, multi-tenancy, data deletion.
5. **Build order.** Vertical slice (the core loop, ugly, end to end) then must-haves by area, should, could, then the fixes `/dynamia-remix:voice` finds. Each milestone lists its S-IDs, tables and routes.

## Output

The files above and a summary: stack in one line, table and route counts, the three riskiest parts, next step `/dynamia-remix:build`.
