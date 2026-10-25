---
name: performance
description: Finds slow queries from performance_schema digests and explains lock waits, long transactions and the latest deadlock on MySQL, Percona or MariaDB, read-only, with mysql-tool slow-queries and locks. Use when the database is slow, connections pile up, queries time out, or the user asks about locks or deadlocks.
---

# performance

Read-only. It suggests; it never creates an index, changes a setting or kills a session.

## Slow queries

1. `python3 ${CLAUDE_PLUGIN_ROOT}/bin/mysql-tool slow-queries <profile> [--limit 10]`: the heaviest normalized statements by total time, with calls, average, and flags (no usable index, many rows read per row returned). Digests hold `?` instead of values.
2. If `performance_schema` is off (MariaDB ships it off), say so: enabling it needs a config change and a restart, which is a critical operation. Use the slow query log meanwhile.
3. For a candidate: `mysql-tool query <profile> "EXPLAIN SELECT ..."` (write the statement with real column names, not user data) and read the plan before suggesting an index. A proposed `CREATE INDEX` is text for the user; on a big table it can lock or take hours.

## Locks

1. `mysql-tool locks <profile>`: open transactions oldest first, who waits for whom, and the latest deadlock. A transaction open for minutes with few rows changed is usually an application that forgot to commit.
2. Name the blocker (thread id, age, last statement shortened). `KILL <id>` is the user's decision, with the risk stated (rollback of a big transaction can take as long as the work did).

Query text can contain data. Quote the minimum.
