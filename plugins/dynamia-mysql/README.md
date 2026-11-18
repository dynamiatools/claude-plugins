# dynamia-mysql

Safe work on MySQL, Percona Server and MariaDB: connect without leaking passwords, analyze a database, check replication, build a new replica. Supports MySQL and Percona 8.4 and later, and MariaDB 10.11 and later. Python 3.11+ standard library only; it uses the `mysql` or `mariadb` client binary.

| Skill | Use it to |
|---|---|
| `/dynamia-mysql:connect` | Save connections (workspace `.dynamia/mysql/connections.json` or user folder), store a secret, detect flavor and version |
| `/dynamia-mysql:inspect` | Read-only analysis: settings, load, sizes, risks |
| `/dynamia-mysql:query` | Read-only SQL on a connection: explore tables, look at rows, count, with a row cap and time limit |
| `/dynamia-mysql:replication` | Replica health: threads, lag, errors, GTID |
| `/dynamia-mysql:replica-setup` | Build a new replica with XtraBackup, mariabackup, CLONE or a dump, step by step |
| `/dynamia-mysql:safe-ops` | Restart, move a datadir, restore, change settings, with a confirmation for each |
| `/dynamia-mysql:backup` | Take a physical or logical backup, verify the files, prove it restores |
| `/dynamia-mysql:repair` | Diagnose a broken replica: connection, purged logs, errant GTIDs, divergence |
| `/dynamia-mysql:failover` | Plan a switchover or failover with GTID checks and a confirmed runbook |
| `/dynamia-mysql:audit` | Risky settings, accounts without TLS or open to any host, secrets left in files |
| `/dynamia-mysql:performance` | Slow queries from performance_schema, lock waits, long transactions, deadlocks |
| `/dynamia-mysql:schema-diff` | Compare tables, columns and indexes of two servers |
| `/dynamia-mysql:upgrade-check` | What breaks moving MySQL or Percona 8.0 to 8.4 |
| `/dynamia-mysql:monitor` | One line per server for a quick check or cron, with an exit code |

## Safety model

- **Passwords:** never in argv, profiles, output or the transcript. Secrets live in `~/.config/dynamia-mysql/secrets.env` (mode 600), reach the client through a temporary 0600 option file, and are redacted from everything the tool prints. The user sets them with `! mysql-tool secret-set NAME`; SQL uses `'@@ENV:NAME@@'`.
- **Read-only by default:** `mysql-tool query` runs one SELECT, SHOW, DESCRIBE or EXPLAIN SELECT in a read-only session, capped at 200 rows (`--limit`) and 30 seconds (`--timeout`), with `--db` for the default schema.
- **Saved connections:** `conn-add`, `conn-list`, `conn-remove` and `conn-trust` keep connections in `.dynamia/mysql/connections.json` (workspace, shared through the repo) or in the user folder (`connections.json`, mode 600). They hold a secret's *name*, never a password; `env` and `confirm` are honored only in `profiles.toml`; a workspace connection must be trusted once per machine (`conn-trust`) before it is used, so a cloned repo cannot send a secret to another host.
- **Narrow writes:** `mysql-tool exec` only accepts the replication-setup statements, each checked end to end (an exact privilege list, one account, one assignment, known CHANGE options). Only `REPL_` and `CLONE_` secrets can be sent to another server. Destructive statements are never run by `exec`. MySQL client commands (`\!`, `source`, `system`, `tee`) are refused, and comments are stripped before the statement is sent.
- **Test servers:** a destructive statement is judged by where it runs, not only by its text. The user marks a profile `env = "test"` in `profiles.toml` (the default is `prod`, and an unknown host is never a test one). `mysql-tool exec-test PROFILE "SQL"` then runs one DROP DATABASE/SCHEMA/TABLE/VIEW, TRUNCATE, DELETE, UPDATE, RESET BINARY LOGS AND GTIDS or PURGE BINARY LOGS on that profile only: it refuses any other profile, the server's own system schemas (`mysql`, `sys`, `information_schema`, `performance_schema`), stacked statements, client commands and secret placeholders, and writes a private trail to `exec-test.log` next to the secrets. The hook asks the user before each one. For a throwaway server on this machine the user can add `confirm = false` to that profile (off by default, honored only for `localhost`, `127.0.0.1` or `::1`) and the hook stops asking. A raw `mysql -e` with a destructive statement stays denied for every server, because the hook cannot know where it goes.
- **Hook `mysql-guard`** (PreToolUse on Bash, Read and Grep, silent outside MySQL commands, fails open): denies passwords in commands, reading the secrets folder, `~/.my.cnf`, `/etc/mysql` and account hashes, and destructive statements (DROP, TRUNCATE, DELETE or UPDATE without WHERE, RESET BINARY LOGS, PURGE, removing a datadir); asks the user before write SQL, restarts, moving or copying a datadir, restores, CLONE and replication changes. It is a guard against mistakes, not a sandbox: a command assembled at run time, an encoded string or a script file can slip past a text match, so the tool's own checks (read-only session, allowlist, no placeholders in queries) are the real barrier.

- **Run an app with a connection:** `mysql-tool run NAME --env VAR=TEMPLATE ... -- COMMAND` starts COMMAND with the variables filled from the saved connection (`{host} {port} {user} {password} {db}`), so the app keeps its own variable names. The password goes only into that child's environment, never into argv, and the child's output is redacted. The guard asks for confirmation on every `run`, because the command receives the password.

Tools: `bin/mysql-tool` (`profiles`, `conn-add`, `conn-list`, `conn-remove`, `conn-trust`, `run`, `secrets`, `secret-set`, `secret-gen`, `info`, `inspect`, `query`, `exec`, `exec-test`, `replica-status`, `plan-replica`, `diagnose`, `plan-failover`, `backup`, `verify-backup`, `audit-config`, `audit-accounts`, `scan-secrets`, `slow-queries`, `locks`, `schema-diff`, `upgrade-check`, `monitor`) and `bin/mysql-guard`.

Install:

```
/plugin marketplace add dynamiatools/claude-plugins
/plugin install dynamia-mysql@dynamia-tools
```

Tests: `python3 -m unittest discover -s tests` (fake client, no database needed).

Live-tested on 2026-10-25 against Docker servers (MySQL 8.4.13, Percona Server 8.4.11, MariaDB 11.4.13, MariaDB 10.11, MySQL 8.0.46) with the real clients, XtraBackup 8.4 and mariabackup: connect, inspect, audits, slow queries, locks and deadlocks, schema diff, upgrade check, monitor; building replicas by XtraBackup (MySQL and Percona), mariabackup, CLONE and dump (MySQL and MariaDB); diagnosing a wrong port, errant GTIDs, a missing row and purged binary logs; a MySQL and a MariaDB switchover and a MySQL failover; and the hook and a skill inside a real Claude Code session. Not live-tested: Percona CLONE, MariaDB failover with a dead source, TLS with verified certificates, GTID gaps across several MariaDB domains, replication over a real network.
