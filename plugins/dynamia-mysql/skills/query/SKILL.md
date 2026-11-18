---
name: query
description: Runs read-only SQL queries on a MySQL, Percona or MariaDB connection with mysql-tool query - explore databases and tables, look at rows, count, aggregate, check a plan - with a row cap and a time limit. Use when the user asks to query, look up, count or show data in a database, or to see what a table holds.
---

# query

Read-only. `mysql-tool query` runs **one** `SELECT`, `SHOW`, `DESCRIBE` or `EXPLAIN SELECT` in a read-only session. It refuses writes, `INTO OUTFILE`, locking reads, `SLEEP`/`GET_LOCK`, stacked statements, secret placeholders and account hashes. A change to data goes to the user as a statement to review; this skill never runs it.

```
python3 ${CLAUDE_PLUGIN_ROOT}/bin/mysql-tool query <profile> "SELECT ..." [--db SCHEMA] [--limit N] [--timeout S] [--json]
```
- `<profile>`: a saved connection (`mysql-tool conn-list`; create one with `/dynamia-mysql:connect`, which saves it to the workspace `.dynamia/mysql/connections.json` or to the user folder). If none exists, go there first. Never ask for or print a password.
- `--db`: default schema, so `FROM orders` works; a connection saved with `--db` uses it automatically. Without either, qualify tables (`shop.orders`).
- `--limit` (default 200, `0` = no cap): rows returned. When the result is cut, a `-- truncated` note appears on stderr; narrow the query instead of raising the cap.
- `--timeout` (default 30 s): the server stops the statement after this time.
- `--json`: a list of row objects, better when you will process the result.

## How to work
1. **Discover before querying.** `SHOW DATABASES`, `SHOW TABLES FROM <db>`, `DESCRIBE <db>.<table>` (or `information_schema.columns`). Do not guess column names.
2. **Ask for what the question needs**: named columns, a `WHERE`, `ORDER BY` + `LIMIT`, or `COUNT(*)` / `GROUP BY`, not `SELECT *` on a big table. Start with a count or `LIMIT 5` to see the shape.
3. **Check cost on big tables**: `EXPLAIN SELECT ...` first. A full scan of a large table with no filter is a reason to add a filter (date range, id) or to ask the user.
4. **Report** the numbers or rows that answer the question, say how many rows were seen and whether the result was truncated, and quote the SQL you ran.

## Care with data
- Tables can hold personal or secret data (emails, documents, tokens, password hashes). Select only the columns the question needs, and do not paste sensitive values you did not need to see; mask or count instead.
- A result is a snapshot: on a busy server, say so when exact totals matter.
- The tool refuses `mysql.user` and replication password tables; for accounts use `/dynamia-mysql:audit`.
- On a production primary prefer a replica profile when one exists, and keep queries short.

## When it is not a query
Slow queries and locks: `/dynamia-mysql:performance`. Server health and sizes: `/dynamia-mysql:inspect`. Compare two schemas: `/dynamia-mysql:schema-diff`. Anything that changes data or the server: `/dynamia-mysql:safe-ops`, with the user's confirmation.
