---
name: replica-setup
description: Builds a new replica of a MySQL, Percona Server or MariaDB source with GTID, by physical backup (XtraBackup or mariabackup), CLONE (MySQL/Percona) or dump. Checks every prerequisite first, prints a runbook, and confirms each critical step with the user. Use when the user asks to create, add, rebuild or repair a replica.
---

# replica-setup

Needs profiles for the source and the new replica (`/dynamia-mysql:connect`), a decision on the method, and a backup you trust (`/dynamia-mysql:backup`). Default: physical backup plus GTID. CLONE is MySQL/Percona only and erases the target. A dump is for small data.

## Rules

- **Never** run a step that is not in the runbook, and never improvise destructive commands. `RESET BINARY LOGS AND GTIDS`, `DROP`, `PURGE` and removing a datadir are for the user to run by hand if they decide to.
- **Confirm every `[CONFIRM]` step** with the user in plain words before running it: what it does, on which host, what it replaces, how to undo it. The guard hook asks again for restarts, moves of the datadir, restores, `CLONE`, `STOP/START/CHANGE` of replication and `SET GLOBAL`.
- **Never replace a datadir** without moving the old one aside, and never in the same step as stopping the server: stop it, check it is down, only then move. Restore with `--copy-back`, so the backup survives a retry.
- `CLONE INSTANCE` runs in the background (minutes to hours): poll `performance_schema.clone_status`, never start a second one. Check free disk (data size and 2x) first.
- **Passwords:** a secret for the replication account via `! mysql-tool secret-gen REPL_PW`; SQL uses `'@@ENV:REPL_PW@@'`; backup tools use a 0600 option file the user creates, never `--password`. Never print or read secrets.
- The shell on a server may not be this machine. Commands for another host are shown to the user, or run only if this session is on that host.

## Steps

1. Plan: `python3 ${CLAUDE_PLUGIN_ROOT}/bin/mysql-tool plan-replica --source <p> --replica <p> --method xtrabackup|mariabackup|clone|dump`. It checks flavor family (MySQL and Percona together, MariaDB alone), release series, `server_id`, `server_uuid`, binary log, GTID on both sides, page size and OS for physical copies, and the state of the target: it blocks when the target already holds data, already replicates, looks like a primary, or has replicas of its own. `--rebuild` lifts the first two, only after the user agreed to replace that server's data; replicas attached to the target always block. With blockers, report them and stop; fix the cause, do not bypass it. Enabling GTID on a running MySQL source is a staged online change: explain it and let the user do it.
2. Say out loud which host is the source and which is the replica that will be replaced (the runbook's first step lists both) and get a yes: swapped roles are the worst mistake here. Show the user the runbook and the data size; agree on hosts, paths, service name, backup directory, and the time window (a physical backup of a busy source adds I/O).
3. Run the steps in order, one at a time, with confirmation on `[CONFIRM]`. After each, check the result before the next (`mysql-tool query`, `ls`, the tool's exit code).
4. Position: MySQL/Percona uses `SOURCE_AUTO_POSITION=1` and, only if the restored `gtid_executed` is empty, `gtid_purged` from `xtrabackup_binlog_info`. MariaDB uses `gtid_slave_pos` from `xtrabackup_binlog_info` and `MASTER_USE_GTID=slave_pos`. MySQL 8.4 removed `CHANGE MASTER`, `START SLAVE`, `SHOW SLAVE STATUS` and `MASTER_*` options: use the `SOURCE`/`REPLICA` names there. MariaDB uses `CHANGE MASTER TO` and, since 10.5, `START REPLICA`.
5. Verify with `/dynamia-mysql:replication` until lag is 0 and both threads run. Keep `read_only` on the replica. Keep the backup until it has run a day.

If a step fails, stop. Do not retry with other flags. Report the error text (the tool redacts secrets), the state of both servers, and what is safe to do next. Say what was not verified.
