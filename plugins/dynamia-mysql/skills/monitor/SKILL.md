---
name: monitor
description: One-line health check of one or many MySQL, Percona or MariaDB servers with mysql-tool monitor - reachable, version, uptime, connection use, read_only and replica state - with an exit code for cron. Use when the user asks for a quick status of the servers, a health check, or a script for cron or an alert.
---

# monitor

Read-only and cheap: three small queries per server.

1. `python3 ${CLAUDE_PLUGIN_ROOT}/bin/mysql-tool monitor <profile> [<profile> ...] [--max-lag 30]` prints one line each: `OK|WARN|DOWN name flavor version up=Nd conn=used/max ro=0|1 repl=OK|LAGGING|BROKEN|NONE`, with the reasons after `<-`. Exit 0 if all are fine, 1 otherwise.
2. A WARN is connections at 85% or more, a broken replica, or lag over the limit. DOWN shows the first line of the connection error, with secrets redacted.
3. Lag from `Seconds_Behind_Source` can mislead (it is 0 when the IO thread is stuck): read the reasons, and use `/dynamia-mysql:replication` for the full status.
4. For cron, the profile and its secret must exist for that user (`~/.config/dynamia-mysql`). Never put a password in the crontab. The script that sends the alert is the user's.
