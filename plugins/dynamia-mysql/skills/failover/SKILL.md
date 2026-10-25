---
name: failover
description: Plans a switchover (the old source is alive) or a failover (it is down) to promote a replica in MySQL, Percona or MariaDB, with mysql-tool plan-failover - checks GTIDs and lag, lists blockers, and gives a confirmed step-by-step runbook. Use when the user asks to promote a replica, move the primary, switch roles or recover from a dead source.
---

# failover

The riskiest operation in this plugin. The tool plans; it promotes nothing by itself.

1. Plan: `python3 ${CLAUDE_PLUGIN_ROOT}/bin/mysql-tool plan-failover --candidate <p> [--old-source <p>] [--other <p> ...]`. Without `--old-source`, or with it unreachable, the plan is a failover and warns that anything the old source committed and had not sent is lost.
2. Blockers stop the plan: the candidate is not a healthy replica, has no binary log or `log_replica_updates`, or lacks transactions the old source has (GTID subtraction on MySQL/Percona; equal `gtid_current_pos` on MariaDB). Fix the cause; never bypass a blocker.
3. Before the first step, tell the user in plain words: who becomes primary, which applications will break, the expected downtime, and what is lost in a failover. Get a yes for the whole plan, then a yes for every `[CONFIRM]` step.
4. The plan makes the old source read-only, waits for the candidate to catch up, stops replication on the candidate, opens it for writes, repoints the other replicas with `SOURCE_AUTO_POSITION=1` (MariaDB: `MASTER_USE_GTID=slave_pos`), and turns the old source into a replica kept read-only.
5. `RESET REPLICA ALL` is a manual step for the user: the tool refuses it. So do `KILL`, and pointing applications at the new primary (DNS, proxy, connection strings).
6. Verify every server with `mysql-tool replica-status <profile>`. Keep the old source untouched until it is understood. If a step fails, stop and report the state of every server; do not improvise.
