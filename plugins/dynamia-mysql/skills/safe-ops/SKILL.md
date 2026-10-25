---
name: safe-ops
description: Procedure for the critical operations on a database server - restart or stop mysqld, move or replace a datadir, restore a backup or dump, change settings, anything that destroys data - with the confirmation each one needs. Use whenever the user asks for one of these, or when another dynamia-mysql step reaches one.
---

# safe-ops

The guard hook (`mysql-guard`) already blocks destructive statements and asks for the rest. This skill is how to behave around it. The hook is a guard against mistakes, not a sandbox; the rules below apply even where it cannot see.

## Before any critical operation

1. State it: the exact command, the host, what it changes, what it replaces, what it costs (downtime, lost writes, disk), and how to undo it.
2. Check the state: `mysql-tool info`, free disk, a recent backup that was tested, who else is connected (`mysql-tool query <p> "SHOW PROCESSLIST"`). On a source or only copy of data, no recent backup means no go.
3. Ask the user a direct yes or no for that operation. A yes covers that one operation on that host, not the next one.
4. Run it once. Check the result. Report what happened.

## By operation

- **Restart or stop the server:** check the replicas first (`/dynamia-mysql:replication`), warn that connections drop, prefer a clean shutdown (`systemctl stop`, never `kill -9`), and confirm it came back (`mysql-tool info`). Config changes that need a restart are listed before, not discovered after.
- **Move or replace a datadir:** stop the server, `mv` the old directory aside with a dated name (never `rm`), restore into a fresh one, fix ownership (`chown -R mysql:mysql`), SELinux/AppArmor contexts, start, verify. Keep the old copy until the user deletes it.
- **Restore a backup or dump:** into a new or empty instance whenever possible, not over live data. Say what it overwrites. A physical restore needs the server stopped and the backup prepared; a dump restore needs the target schema state spelled out. Verify row counts afterwards.
- **Change a setting:** `SET GLOBAL` is lost at restart unless also written to the config file; `SET PERSIST` survives. Say which. Never change durability (`sync_binlog`, `innodb_flush_log_at_trx_commit`) or `read_only` on a live source without a yes.
- **Drop, truncate, delete without WHERE, purge or reset binary logs, remove a datadir:** do not run them. Explain the consequence and give the user the statement to run themselves if they decide so. The hook denies these.

Never put a password in a command or in the transcript, and never read the secrets file.
