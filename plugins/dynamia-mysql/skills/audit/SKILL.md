---
name: audit
description: Security and configuration audit of a MySQL, Percona or MariaDB server - risky settings, accounts open to any host or without TLS, excess privileges, and passwords left in files or shell history - with mysql-tool. Use when the user asks for a security review, a config check, an account review, or whether secrets leaked.
---

# audit

Read-only. Nothing here changes the server or prints a secret.

1. Settings: `python3 ${CLAUDE_PLUGIN_ROOT}/bin/mysql-tool audit-config <profile>`. Durability, binary log, `binlog_format`, GTID, strict `sql_mode`, `local_infile`, name resolution, log purging, TLS requirement. Findings are `[warn]` or `[info]`; explain each and say whether fixing it needs a restart.
2. Accounts: `mysql-tool audit-accounts <profile>`. Anonymous users, `'%'` hosts, network accounts without TLS, SUPER, GRANT, FILE and SHUTDOWN holders, `mysql_native_password`, expired passwords. It reads only non-secret columns of `mysql.user`, never hashes.
3. Leaks on this machine: `mysql-tool scan-secrets [path ...]`. With no path it checks `~/.my.cnf`, shell and MySQL histories and the profiles file; give a project path to scan a repo. It prints `file:line: kind`, never the value, and notes files readable by others. If something is found, tell the user which file and line, and that the password must be rotated, not just deleted.
4. Report risks first, then the fix as text for the user. This skill changes nothing: a `REVOKE`, `ALTER USER` or `SET GLOBAL` is a critical operation (`/dynamia-mysql:safe-ops`).

Say what was not checked: network exposure, OS permissions of the datadir, backups, application-side secrets.
