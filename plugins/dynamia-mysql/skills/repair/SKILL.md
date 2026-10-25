---
name: repair
description: Diagnoses a broken MySQL, Percona or MariaDB replica with mysql-tool diagnose and picks the safe way out - connection problem, purged binary logs, errant GTIDs or data divergence - without skipping transactions. Use when replication stopped, the SQL thread has an error, or the user asks how to fix a replica.
---

# repair

`/dynamia-mysql:replication` says whether a replica is broken. This says why and what is safe.

1. Run `python3 ${CLAUDE_PLUGIN_ROOT}/bin/mysql-tool diagnose <replica_profile> --source <source_profile>`. The verdict is one of:
   - `CONNECTION`: the IO thread cannot reach or log in. Fix network, firewall, account, TLS. Then `START REPLICA`, with the user's yes.
   - `REBUILD`: error 1236 or purged logs; the source no longer has what the replica needs. Rebuild with `/dynamia-mysql:replica-setup`.
   - `ERRANT` (MySQL/Percona): the replica holds transactions the source never had; the output lists them. Someone wrote on the replica. Find who, keep `read_only` and `super_read_only` ON, and prefer a rebuild.
   - `DIVERGED`: the SQL thread failed and no errant GTID explains it; a row differs or is missing. Compare the table with the source, repair that table by hand, or rebuild.
   - `LAGGING`: it runs but is behind; this is a performance question, not a repair.
2. **Never skip a transaction** (`sql_replica_skip_counter`, injecting an empty GTID) as a fix. It hides the divergence and the replica keeps drifting. Only the user may decide that, in words, after seeing the row that differs.
3. For MariaDB the tool reports the error and the positions; it cannot subtract GTID sets there, so say that the errant check was not done.
4. After any fix, run `mysql-tool replica-status <replica_profile>` until lag is 0, and report what was repaired and what was not verified.

`STOP REPLICA`, `START REPLICA`, `RESET REPLICA` and a rebuild are critical: ask first (`/dynamia-mysql:safe-ops`).
