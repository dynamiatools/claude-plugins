---
name: inspect
description: Analyzes a MySQL, Percona or MariaDB database read-only with mysql-tool inspect and query - version, key settings, load, schema sizes, largest tables, tables without primary key, non-InnoDB tables, open accounts, binary log and GTID state. Use when the user asks to analyze, audit, review or health-check a database or server.
---

# inspect

Everything here is read-only: `mysql-tool query` accepts one SELECT, SHOW, DESCRIBE or EXPLAIN SELECT, runs in a read-only session, and refuses `INTO OUTFILE`, locks and multi-statement input.

1. Run `python3 ${CLAUDE_PLUGIN_ROOT}/bin/mysql-tool inspect <profile>` (profiles: `/dynamia-mysql:connect`).
2. Read the output and report in this order: version and baseline, risks first (binary log off, no GTID, `binlog_format` not ROW, relaxed durability, accounts open to `%` or anonymous), then the biggest schemas and tables, then load numbers.
3. For a question the report does not answer, use `mysql-tool query <profile> "SELECT ..."`. Query `information_schema` and `performance_schema`; never `mysql.user` password columns.
4. For a slow query, `EXPLAIN SELECT ...` first and read the plan before suggesting an index. A suggestion is text for the user; this skill does not create indexes or alter tables.

Do not change anything on the server from this skill. A fix that needs a write (an index, a setting, an account) goes to the user as a statement to review. Settings you propose should say whether they need a restart.

Next steps: `/dynamia-mysql:replication` to check replicas, `/dynamia-mysql:replica-setup` to build one.
