# dynamia-mysql

Safe work on MySQL, Percona Server and MariaDB: connect without leaking passwords, analyze a database, check replication, build a new replica. Supports MySQL and Percona 8.4 and later, and MariaDB 10.11 and later. Python 3.11+ standard library only; it uses the `mysql` or `mariadb` client binary.

| Skill | Use it to |
|---|---|
| `/dynamia-mysql:connect` | Add a server profile, store a secret, detect flavor and version |
| `/dynamia-mysql:inspect` | Read-only analysis: settings, load, sizes, risks |
| `/dynamia-mysql:replication` | Replica health: threads, lag, errors, GTID |
| `/dynamia-mysql:replica-setup` | Build a new replica with XtraBackup, mariabackup, CLONE or a dump, step by step |
| `/dynamia-mysql:safe-ops` | Restart, move a datadir, restore, change settings, with a confirmation for each |

## Safety model

- **Passwords:** never in argv, profiles, output or the transcript. Secrets live in `~/.config/dynamia-mysql/secrets.env` (mode 600), reach the client through a temporary 0600 option file, and are redacted from everything the tool prints. The user sets them with `! mysql-tool secret-set NAME`; SQL uses `'@@ENV:NAME@@'`.
- **Read-only by default:** `mysql-tool query` runs one SELECT, SHOW, DESCRIBE or EXPLAIN SELECT in a read-only session.
- **Narrow writes:** `mysql-tool exec` only accepts the replication-setup statements. Destructive statements are never run by the tool.
- **Hook `mysql-guard`** (PreToolUse on Bash and Read, silent outside MySQL commands, fails open): denies passwords in commands, reading the secrets file and destructive statements (DROP, TRUNCATE, DELETE or UPDATE without WHERE, RESET BINARY LOGS, PURGE, removing a datadir); asks the user before write SQL, restarts, moving or copying a datadir, restores, CLONE and replication changes. It is a guard against mistakes, not a sandbox.

Tools: `bin/mysql-tool` (`profiles`, `secrets`, `secret-set`, `secret-gen`, `info`, `inspect`, `query`, `exec`, `replica-status`, `plan-replica`) and `bin/mysql-guard`.

Install:

```
/plugin marketplace add dynamiatools/claude-plugins
/plugin install dynamia-mysql@dynamia-tools
```

Tests: `python3 -m unittest discover -s tests`. They use a fake client, so they need no database. Replica setup is checked against the MySQL 8.4, Percona XtraBackup 8.4, mariabackup and MariaDB documentation; it has not been run against live servers.
