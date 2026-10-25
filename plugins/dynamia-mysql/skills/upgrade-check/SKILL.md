---
name: upgrade-check
description: Checks a MySQL or Percona 8.0 server before upgrading to 8.4 with mysql-tool upgrade-check - removed variables set in the config, mysql_native_password accounts, spatial indexes, changed defaults - and guides the upgrade order. Use when the user plans to move to MySQL or Percona 8.4 or asks what an upgrade will break.
---

# upgrade-check

Read-only. It does not upgrade anything.

1. `python3 ${CLAUDE_PLUGIN_ROOT}/bin/mysql-tool upgrade-check <profile>`. For 8.0 it finds variables removed in 8.4 that are set explicitly (read from `performance_schema.variables_info`, so defaults are not flagged), accounts on `mysql_native_password` (no longer enabled by default), spatial indexes (drop before upgrading to 8.4.4 or later and recreate after), and lists the changed defaults to review.
2. MariaDB: the tool has no verified rule list and says so. Read the release notes between the two versions, then follow the same order below.
3. Also run what the tool cannot: MySQL Shell `util.checkForServerUpgrade()` and `mysqlcheck --check-upgrade`. Confirm the supported path and minimum 8.0 release in the MySQL "Upgrade Paths" page; the tool does not check the patch level.
4. Order: tested backup (`/dynamia-mysql:backup`, restore proven), replicas first, then switchover (`/dynamia-mysql:failover`), then the old source. Upgrades and restarts are critical operations: follow `/dynamia-mysql:safe-ops`, one server at a time, verify replication after each.
5. A removed variable in the config file stops the server from starting. List them for the user to remove before the restart.

Report what was checked and what was not. A clean result from this tool is not a clean bill for the upgrade.
