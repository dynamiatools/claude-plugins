---
name: connect
description: Sets up and tests a connection to a MySQL, Percona Server or MariaDB server with mysql-tool, without ever exposing a password, and detects the flavor and version. Use before any other MySQL work, or when the user asks to connect to a database server, add a server profile or store a database password.
---

# connect

Supported: MySQL and Percona Server 8.4 and later, MariaDB 10.11 and later. Older servers are reported as unsupported; do not use the replication commands on them.

## Password rules (never break these)

- A password never appears in a command, a profile, a file you write, or your answer. The tool reads it from `~/.config/dynamia-mysql/secrets.env` (mode 600) and gives it to the client through a temporary 0600 option file. A guard hook denies `-pSECRET`, `--password=`, `MYSQL_PWD=`, literal passwords in SQL, and the obvious ways to read the secrets folder, its temporary files, `~/.my.cnf` or `/etc/mysql`. It is a guard against mistakes, not a sandbox: never try to get around it, and never read those files by any other route.
- You cannot type a secret for the user. Tell them to run it themselves in this prompt:
  `! python3 ${CLAUDE_PLUGIN_ROOT}/bin/mysql-tool secret-set PROD_DB_PW`
  For a password you must create (a replication user), they run `secret-gen REPL_PW` and nobody sees it.
- In SQL, write `'@@ENV:REPL_PW@@'`. The tool substitutes the value at run time. Only secrets named `REPL_...` or `CLONE_...` may be sent to another server (replication and clone accounts); a login secret such as `PROD_DB_PW` can never be placed in SQL, and placeholders are refused in `query`.
- A secret needs 8 or more characters and no quotes, backslashes or control characters.
- Read `profiles.toml` with the Read tool if needed; it holds no secrets. Never `cat` or `grep` the folder.

## Steps

1. Ask for host, port, user and which secret name holds the password (or a `mysql_config_editor` login path on MySQL). Prefer an account with read-only grants for analysis.
2. Write `~/.config/dynamia-mysql/profiles.toml` (no secret in it; a key containing "pass" is refused):

```toml
[profiles.prod]
host = "db1.example.com"
port = 3306
user = "dba_ro"
secret = "PROD_DB_PW"
ssl_mode = "REQUIRED"      # optional. A MariaDB 11.x client insists on TLS: for a server without it (MariaDB 10.x by default) set "DISABLED", only on a trusted network
# client = "mariadb"       # optional, default: mysql, then mariadb
```

3. Check it: `python3 ${CLAUDE_PLUGIN_ROOT}/bin/mysql-tool info prod`. Report flavor, version, whether it is supported, `server_id`, binary log and GTID state.
4. Remote SSL is the default expectation. If `ssl_mode` is missing on a non-local host, say so.

`mysql-tool profiles` and `mysql-tool secrets` list names only, never values. Next: `/dynamia-mysql:inspect`.
