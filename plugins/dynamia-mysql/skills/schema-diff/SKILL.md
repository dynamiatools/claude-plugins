---
name: schema-diff
description: Compares the schema of two MySQL, Percona or MariaDB servers - tables, columns, types, indexes, engines - with mysql-tool schema-diff, for example a source and its replica, or staging and production. Use when the user asks whether two databases have the same structure, after a migration, or when a replica broke on a missing table.
---

# schema-diff

Read-only. Structure only: no rows, no defaults, no column order.

1. `python3 ${CLAUDE_PLUGIN_ROOT}/bin/mysql-tool schema-diff --a <profile> --b <profile> [--schema <name>]`. Exit 1 means differences; the output lists tables, columns and indexes present in only one side and those whose type, null flag, collation, columns or uniqueness differ. System schemas are skipped.
2. Compare like with like. MySQL and MariaDB differ in collations and type spellings, so across families expect noise; say so rather than reporting every line as a bug.
3. Explain the effect: a column missing on a replica breaks row-based replication; a missing index only slows it; a different engine changes transaction behavior.
4. The fix is a migration the user runs (`ALTER` is a critical operation, `/dynamia-mysql:safe-ops`). On a replica, DDL applied only there makes it diverge: change the source and let it replicate, or rebuild.
