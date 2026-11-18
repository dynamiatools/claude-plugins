---
name: connect
description: Creates, lists, trusts and removes saved connections to a MySQL, Percona Server or MariaDB server with mysql-tool conn-add, without ever exposing a password, and tests them (flavor and version). Use before any other MySQL work, or when the user asks to connect to a database server, save or add a connection or profile, or store a database password.
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
- Read `profiles.toml` or a `connections.json` with the Read tool if needed; they hold no secrets. Never `cat` or `grep` the folder.

## Steps

1. Ask for host, port, user and which secret name holds the password (or a `mysql_config_editor` login path on MySQL), plus an optional default schema (`db`). Prefer an account with read-only grants for analysis.
2. Ask **where to save it**, with a recommendation:
   - `workspace` (`.dynamia/mysql/connections.json` at the nearest `.dynamia` folder): shared with the team through the repo. It holds no password, only the secret's *name*, so each person sets their own secret. Recommended when the project has a workspace.
   - `user` (`~/.config/dynamia-mysql/connections.json`, mode 600): only this user, any project.
3. Save it (no password anywhere; a key containing "pass" is refused):
   `python3 ${CLAUDE_PLUGIN_ROOT}/bin/mysql-tool conn-add NAME --host H --user U --secret PROD_DB_PW [--port 3306] [--db SCHEMA] [--ssl-mode REQUIRED] [--description "..."] [--scope user|workspace]`
   Without `--scope` it picks the workspace when there is one. If the secret is not set yet, the tool says so: the user runs `! python3 ${CLAUDE_PLUGIN_ROOT}/bin/mysql-tool secret-set PROD_DB_PW`.
4. Check it: `python3 ${CLAUDE_PLUGIN_ROOT}/bin/mysql-tool info NAME`. Report flavor, version, whether it is supported, `server_id`, binary log and GTID state.
5. Remote SSL is the default expectation. If `ssl_mode` is missing on a non-local host, say so. A MariaDB 11.x client insists on TLS: for a server without it (MariaDB 10.x by default) use `--ssl-mode DISABLED`, only on a trusted network.

Manage them: `conn-list` (names, scope, host, user, db, secret name, never a value) and `conn-remove NAME [--scope user|workspace]`.

**Trust.** A connection that came from a workspace file you did not write (a cloned repo, a teammate's commit) is not used until the user trusts it on this machine, because it could point a secret of theirs at another host. The tool refuses it and says so. Show the user `conn-list` (host, user, secret) and, if it is right, they run `! python3 ${CLAUDE_PLUGIN_ROOT}/bin/mysql-tool conn-trust NAME`. Changing the host, port, user, secret, socket, login path or client of a trusted connection asks for trust again. Connections added with `conn-add` here are trusted already.

**Precedence** for a name: `profiles.toml`, then the workspace file, then the user file. `env = "test"` and `confirm` are honored only in `profiles.toml` (below), never in a connection file, so a shared file cannot loosen the destructive-SQL guard.

## Run an app with a saved connection

When the user says "use the connection X to launch the app", find the variable names the app expects (its config, `.env.example` or docs; never guess) and run:
`python3 <plugin>/bin/mysql-tool run X --env SPRING_DATASOURCE_URL=jdbc:mysql://{host}:{port}/{db} --env SPRING_DATASOURCE_USERNAME={user} --env SPRING_DATASOURCE_PASSWORD={password} -- ./mvnw spring-boot:run`
Fields: `{host} {port} {user} {password} {db}`. The password is placed only in the child's environment, and its output is redacted. A long-lived app goes in the background. The guard asks the user to confirm each `run`. Never echo or print those variables.

## Advanced: `profiles.toml`

Still supported, and the only place to mark a disposable server for `mysql-tool exec-test`. Write `~/.config/dynamia-mysql/profiles.toml` (no secret in it):

```toml
[profiles.prod]
host = "db1.example.com"
port = 3306
user = "dba_ro"
secret = "PROD_DB_PW"
ssl_mode = "REQUIRED"      # optional
# client = "mariadb"       # optional, default: mysql, then mariadb
# env = "test"             # optional, default "prod". Only the user marks a server as disposable; it allows `mysql-tool exec-test` there
# confirm = false          # optional, only with env = "test" on localhost: exec-test then runs without asking. Leave it off unless the user asks
```

`mysql-tool conn-list`, `profiles` and `secrets` list names only, never values. Next: `/dynamia-mysql:inspect`.
