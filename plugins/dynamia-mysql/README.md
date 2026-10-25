# dynamia-mysql

Safe work on MySQL, Percona Server and MariaDB: connect without leaking passwords, analyze a database, check replication, build a new replica. Supports MySQL and Percona 8.4 and later, and MariaDB 10.11 and later. Python 3.11+ standard library only; it uses the `mysql` or `mariadb` client binary.

| Skill | Use it to |
|---|---|
| `/dynamia-mysql:connect` | Add a server profile, store a secret, detect flavor and version |
| `/dynamia-mysql:inspect` | Read-only analysis: settings, load, sizes, risks |
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
- **Read-only by default:** `mysql-tool query` runs one SELECT, SHOW, DESCRIBE or EXPLAIN SELECT in a read-only session.
- **Narrow writes:** `mysql-tool exec` only accepts the replication-setup statements, each checked end to end (an exact privilege list, one account, one assignment, known CHANGE options). Only `REPL_` and `CLONE_` secrets can be sent to another server. Destructive statements are never run by the tool. MySQL client commands (`\!`, `source`, `system`, `tee`) are refused, and comments are stripped before the statement is sent.
- **Hook `mysql-guard`** (PreToolUse on Bash, Read and Grep, silent outside MySQL commands, fails open): denies passwords in commands, reading the secrets folder, `~/.my.cnf`, `/etc/mysql` and account hashes, and destructive statements (DROP, TRUNCATE, DELETE or UPDATE without WHERE, RESET BINARY LOGS, PURGE, removing a datadir); asks the user before write SQL, restarts, moving or copying a datadir, restores, CLONE and replication changes. It is a guard against mistakes, not a sandbox: a command assembled at run time, an encoded string or a script file can slip past a text match, so the tool's own checks (read-only session, allowlist, no placeholders in queries) are the real barrier.

Tools: `bin/mysql-tool` (`profiles`, `secrets`, `secret-set`, `secret-gen`, `info`, `inspect`, `query`, `exec`, `replica-status`, `plan-replica`, `diagnose`, `plan-failover`, `backup`, `verify-backup`, `audit-config`, `audit-accounts`, `scan-secrets`, `slow-queries`, `locks`, `schema-diff`, `upgrade-check`, `monitor`) and `bin/mysql-guard`.

Install:

```
/plugin marketplace add dynamiatools/claude-plugins
/plugin install dynamia-mysql@dynamia-tools
```

Tests: `python3 -m unittest discover -s tests` (fake client, no database needed).

Live-tested on 2026-10-25 against Docker servers (MySQL 8.4.13, Percona Server 8.4.11, MariaDB 11.4.13, MariaDB 10.11, MySQL 8.0.46) with the real clients, XtraBackup 8.4 and mariabackup: connect, inspect, audits, slow queries, locks and deadlocks, schema diff, upgrade check, monitor; building replicas by XtraBackup (MySQL and Percona), mariabackup, CLONE and dump (MySQL and MariaDB); diagnosing a wrong port, errant GTIDs, a missing row and purged binary logs; a MySQL and a MariaDB switchover and a MySQL failover; and the hook and a skill inside a real Claude Code session. Not live-tested: Percona CLONE, MariaDB failover with a dead source, TLS with verified certificates, GTID gaps across several MariaDB domains, replication over a real network.
