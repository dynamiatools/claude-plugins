---
name: replication
description: Checks the health of MySQL, Percona or MariaDB replication with mysql-tool replica-status - IO and SQL threads, lag, errors, GTID positioning - across both naming families, and explains what a failure means. Use when the user asks if a replica is healthy, why replication stopped, or how far behind a replica is.
---

# replication

1. For each replica profile: `python3 ${CLAUDE_PLUGIN_ROOT}/bin/mysql-tool replica-status <profile> [--max-lag 30]`. It reads `SHOW REPLICA STATUS` (MySQL/Percona 8.4 names and MariaDB names alike) and answers `OK`, `LAGGING`, `BROKEN` or `NONE` (not a replica), with the reasons. Exit code 1 means a problem.
2. On the source: `mysql-tool query <source> "SHOW REPLICAS"` (MariaDB: `SHOW SLAVE HOSTS`) and `SHOW BINARY LOG STATUS` (MariaDB: `SHOW MASTER STATUS`). Compare GTIDs with `SELECT @@GLOBAL.gtid_executed` (MariaDB: `@@gtid_current_pos`).
3. Explain, do not fix. Common causes:
   - IO thread `Connecting`: network, firewall, wrong host, the replication account or its authentication (`caching_sha2_password` needs SSL or the public key).
   - SQL thread stopped with a duplicate key or missing row: the replica diverged. Do not skip the transaction. Find who wrote on the replica (`read_only` off?) and tell the user.
   - Error about purged binary logs: the replica is too far behind; it needs a rebuild, see `/dynamia-mysql:replica-setup`.
   - Lag that grows: single-thread apply, big transactions, tables without primary key (`/dynamia-mysql:inspect`), slow disk on the replica.
4. If it is broken, run `/dynamia-mysql:repair` for the cause. Promoting a replica is `/dynamia-mysql:failover`.
5. `STOP REPLICA`, `START REPLICA`, `RESET REPLICA` and any change of the source are critical: propose them, explain the risk, and run them only after the user says yes. `mysql-tool exec` allows only the replication statements and refuses everything destructive; the guard hook asks the user as well.

Never skip a transaction (`sql_replica_skip_counter`, empty GTIDs) as a fix; see `/dynamia-mysql:repair`. With several replication channels, the status names the channel of each problem.

Report the numbers you saw. If a replica was not checked, say so.
