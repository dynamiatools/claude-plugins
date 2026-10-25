---
name: backup
description: Takes a physical (XtraBackup, mariabackup) or logical (mysqldump, mariadb-dump) backup of a MySQL, Percona or MariaDB server with mysql-tool, checks it is complete, and proves it restores. Use when the user asks for a backup, to verify a backup, or to test that a backup can be restored.
---

# backup

A backup nobody restored is a hope. This skill makes it, checks it, and restores it somewhere harmless.

## Rules

- **Taking a backup is a critical operation** (heavy I/O on the server, writes files, can lock). Say the method, host, target and window, and get a yes first. The guard hook asks as well.
- Physical backups (`xtrabackup`, `mariabackup`) must run **on the database host**, where the datadir is; the tool refuses when the server's datadir does not exist on this machine. Logical dumps can run anywhere that reaches the server. The target folder is created with mode 0700 (a dump holds account hashes).
- Backups can take hours: run the command in the background, not in a foreground call that can time out. If a run is killed, the temporary option file is swept on the next start, and the target is not to be used.
- The tool never overwrites: the target must not exist or must be empty. It refuses when free space is short (data size x 1.1 physical, x 0.5 dump). Credentials go in a temporary 0600 option file, never in argv or the output.

## Steps

1. Pick the method: physical for big data and for building replicas; dump for small data and for moving between versions. XtraBackup for MySQL/Percona, mariabackup for MariaDB.
2. Look first: `python3 ${CLAUDE_PLUGIN_ROOT}/bin/mysql-tool backup <profile> --method <m> --target <dir> --dry-run` shows data size and free space and writes nothing.
3. Run it without `--dry-run` after the user confirms. It writes `backup-manifest.json` (method, version, size, sha256 for dumps) and keeps a failed target for inspection; never use a failed one.
4. Check it: `python3 ${CLAUDE_PLUGIN_ROOT}/bin/mysql-tool verify-backup <dir>`. It reads the manifest, the checkpoints, the replication position file, the dump's trailer and its hash. It checks files only.
5. Prove it restores, on a scratch instance that is not production (a new datadir and port, `--prepare` on a copy for physical backups, `mysql < dump.sql` for dumps), then count rows of a few tables against the source. Restoring is a critical operation: follow `/dynamia-mysql:safe-ops`. If you could not do this step, say the backup is unproven.

Report: method, size, where it is, what `verify-backup` said, and whether a restore was tested.
