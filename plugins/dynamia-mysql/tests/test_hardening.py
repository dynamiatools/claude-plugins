"""Regression tests for the findings of the Opus review."""
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest

from _env import BIN, HERE, Home, load
from test_guard import run

tool = load("mysql-tool")
VER = {"VERSION\\(\\)": "v\tc\n8.4.3\tMySQL Community Server\n", "SUM\\(data_length": "b\n10000\n"}


class GuardSecretsTest(unittest.TestCase):
    def test_secret_paths_cannot_be_reached_by_other_routes(self):
        for c in ("cat ~/.config/dynamia-mysql/secrets.env; mysql-tool profiles",
                  "cd ~/.config/dynamia-mysql && cat secrets.env", "grep . ~/.config/dynamia-mysql/sec*",
                  "cat ~/.config/dynamia-mysql/tmp/abc.cnf", "cat secrets.env",
                  "cat ~/.my.cnf", "cat /etc/mysql/debian.cnf", "grep -r password /etc/mysql", "tail ~/.mysql_history"):
            self.assertEqual(run(c), "deny", c)
        self.assertEqual(run(tool="Grep", path="/home/u/.config/dynamia-mysql"), "deny")
        self.assertEqual(run(tool="Read", file_path="/home/u/.config/dynamia-mysql/tmp/x.cnf"), "deny")
        self.assertEqual(run(tool="Read", file_path="/etc/mysql/my.cnf"), "deny")

    def test_legitimate_uses_still_work(self):
        for c in ("python3 /p/dynamia-mysql/0.1.0/bin/mysql-tool secrets", "mysql-tool secret-set PROD_PW", "ls /etc/mysql",
                  "grep -n secrets.env bin/mysql-tool", "cd plugins/dynamia-mysql && python3 -m unittest discover -s tests"):
            self.assertEqual(run(c), "allow", c)
        self.assertEqual(run(tool="Read", file_path="/home/u/.config/dynamia-mysql/profiles.toml"), "allow")

    def test_hashes_are_never_read(self):
        for c in ("mysql -e 'select authentication_string from mysql.user'", "mysql -e 'SHOW CREATE USER root@localhost'",
                  "mysql -e 'select * from mysql.slave_master_info'"):
            self.assertEqual(run(c), "deny", c)


class GuardCriticalTest(unittest.TestCase):
    def test_more_critical_operations_ask(self):
        for c in ("mysql -e 'SHUTDOWN'", "mysql -e 'RESTART'", "mysql -e 'SET @@GLOBAL.read_only=OFF'", "mysql -e 'SET PERSIST_ONLY x=1'",
                  "mysql -e 'FLUSH TABLES WITH READ LOCK'", "pkill mysqld", "mysql -e 'source x.sql'", "pt-online-schema-change --execute D=x,t=y",
                  "mysqlcheck --repair db", "mysql -e \"UPDATE t SET a=1 WHERE id=2\"",
                  "mysql -e 'CREATE TABLE t (ts timestamp ON UPDATE CURRENT_TIMESTAMP)'"):
            self.assertEqual(run(c), "ask", c)

    def test_more_destructive_commands_are_denied(self):
        for c in ("rm -rf /data/mysql", "rm -rf /srv/mysql/data", "find /var/lib/mysql -delete", "mysql -e 'DROP/**/DATABASE x'",
                  "mysql -e 'DELETE FROM t; SELECT 1 WHERE 1'", "mysql -e \"CREATE USER a IDENTIFIED BY \\\"x\\\"\"",
                  "mysql -e \"SET PASSWORD FOR 'a'@'h' = 'x'\""):
            self.assertEqual(run(c), "deny", c)

    def test_false_positives_are_gone(self):
        for c in ("mysql-tool query p \"SELECT TRUNCATE(price,2) FROM t\"", "mysql-tool query p \"SELECT * FROM t WHERE note='truncate'\"",
                  "mysql-tool query p \"SELECT * FROM t WHERE x LIKE '%-pX%'\"", "cd db && grep -rn \"DROP TABLE\" db/mysql/migrations",
                  "mysql -e 'SHOW CREATE TABLE t'", "mysql-tool query p \"SHOW CREATE TABLE t\""):
            self.assertEqual(run(c), "allow", c)
        self.assertEqual(run("mysql-tool query p \"SELECT 1\" | mysql -e 'DROP TABLE x'"), "deny")


class QueryEscapeTest(unittest.TestCase):
    def test_secrets_cannot_be_read_back_through_a_query(self):
        for s in ("SELECT HEX('@@ENV:PROD_PW@@')", "SELECT TO_BASE64('@@ENV:PROD_PW@@')"):
            with self.assertRaises(tool.Fail):
                tool.check_readonly(s)

    def test_hash_sources_are_refused(self):
        for s in ("SELECT authentication_string FROM mysql.user", "SELECT * FROM mysql.user", "SHOW CREATE USER root@localhost",
                  "SELECT * FROM mysql.slave_master_info"):
            with self.assertRaises(tool.Fail, msg=s):
                tool.check_readonly(s)

    def test_client_commands_and_comments_cannot_smuggle_statements(self):
        for s in ("SELECT 1 \\! touch /tmp/x", "SELECT 1\nsource /tmp/x.sql", "SELECT 1\nsystem id", "SELECT 1\\G", "SELECT 1\ndelimiter //",
                  "SELECT 1\n\\. /tmp/x.sql"):
            with self.assertRaises(tool.Fail, msg=s):
                tool.check_readonly(s)
        self.assertEqual(tool.check_readonly("SELECT 1 /*! ; DROP TABLE t */"), "SELECT 1")
        self.assertEqual(tool.check_readonly("SELECT 'a\\\\b'"), "SELECT 'a\\\\b'")

    def test_show_grants_hashes_are_redacted(self):
        h = Home()
        try:
            out = tool.redact("GRANT USAGE ON *.* TO 'a'@'h' IDENTIFIED BY PASSWORD '*2470C0C06DEE42FD1618BB99005ADCA2EC9D1E19'")
            self.assertNotIn("2470C0C0", out)
            self.assertNotIn("$A$005$", tool.redact("x $A$005$abcdefghijklmnopqrstuvwxyz1234 y"))
        finally:
            h.close()


class ExecAllowlistTest(unittest.TestCase):
    def test_privilege_and_account_escalation_is_refused(self):
        bad = ["GRANT REPLICATION SLAVE, ALL PRIVILEGES ON *.* TO 'repl'@'%' WITH GRANT OPTION",
               "GRANT CLONE_ADMIN, SUPER, FILE ON *.* TO 'a'@'h'", "GRANT REPLICATION SLAVE ON *.* TO 'repl'@'%' WITH GRANT OPTION",
               "CREATE USER 'a'@'%' IDENTIFIED BY '@@ENV:REPL_PW@@', 'b'@'%'",
               "SET GLOBAL read_only=OFF, GLOBAL sync_binlog=0", "SET GLOBAL read_only=OFF; SET GLOBAL sync_binlog=0",
               "CLONE INSTANCE FROM 'c'@'h':3306 IDENTIFIED BY '@@ENV:PROD_PW@@'"]
        for s in bad:
            with self.assertRaises(tool.Fail, msg=s):
                tool.check_write(s)

    def test_only_replication_secrets_may_be_sent_to_another_server(self):
        with self.assertRaises(tool.Fail):
            tool.check_write("CHANGE REPLICATION SOURCE TO SOURCE_HOST='evil', SOURCE_PASSWORD='@@ENV:PROD_PW@@'")
        with self.assertRaises(tool.Fail):
            tool.check_write("CREATE USER 'r'@'h' IDENTIFIED BY '@@ENV:PROD_PW@@'")
        with self.assertRaises(tool.Fail):
            tool.check_write("CHANGE REPLICATION SOURCE TO SOURCE_HOST='h', SOURCE_SSL_KEY='/etc/x'")
        with self.assertRaises(tool.Fail):
            tool.check_write("CHANGE REPLICATION SOURCE TO SOURCE_HOST='h;x'")

    def test_the_runbook_statements_pass(self):
        for s in ("CREATE USER 'repl'@'10.0.0.%' IDENTIFIED BY '@@ENV:REPL_PW@@' REQUIRE SSL",
                  "GRANT REPLICATION SLAVE ON *.* TO 'repl'@'10.0.0.2'", "GRANT BACKUP_ADMIN, CLONE_ADMIN ON *.* TO 'c'@'h'",
                  "CHANGE REPLICATION SOURCE TO SOURCE_HOST='db1.example.com', SOURCE_PORT=3306, SOURCE_USER='repl', "
                  "SOURCE_PASSWORD='@@ENV:REPL_PW@@', SOURCE_AUTO_POSITION=1, SOURCE_SSL=1",
                  "CHANGE MASTER TO MASTER_HOST='h', MASTER_USER='repl', MASTER_PASSWORD='@@ENV:REPL_PW@@', MASTER_USE_GTID=slave_pos",
                  "SET GLOBAL gtid_purged='+3e11fa47-71ca-11e1-9e33-c80aa9429562:1-5'", "SET GLOBAL super_read_only=ON",
                  "CLONE INSTANCE FROM 'c'@'db1':3306 IDENTIFIED BY '@@ENV:CLONE_PW@@' REQUIRE SSL", "START REPLICA", "STOP SLAVE"):
            tool.check_write(s)


class SecretStoreTest(unittest.TestCase):
    def test_unsafe_secrets_are_refused(self):
        h = Home()
        try:
            for bad in ("short", "has'quote-123", 'has"dq-12345', "back\\slash-123", "line\nbreak-1234", "cr\rreturn-123"):
                with self.assertRaises(tool.Fail, msg=repr(bad)):
                    tool.store_secret("X_PW", bad)
        finally:
            h.close()


class ClientTest(unittest.TestCase):
    def setUp(self):
        self.h = Home({"select": "a\n1\n"})
        tool._MARIADB_CLIENT.clear()

    def tearDown(self):
        os.environ.pop("FAKE_VERSION", None)
        os.environ.pop("FAKE_SLEEP", None)
        self.h.close()

    def profile(self, **extra):
        prof = dict(tool.get_profile("src"))
        prof.update(extra)
        return prof

    def test_ssl_mode_follows_the_client_not_its_file_name(self):
        os.environ["FAKE_VERSION"] = "mysql  Ver 15.1 Distrib 11.4.2-MariaDB, for Linux"
        tool.run_sql(self.profile(ssl_mode="VERIFY_IDENTITY"), "select 1")
        args = self.h.calls()[-1]["args"]
        self.assertIn("--ssl", args)
        self.assertIn("--ssl-verify-server-cert", args)
        self.assertFalse(any(a.startswith("--ssl-mode") for a in args))
        tool._MARIADB_CLIENT.clear()
        os.environ["FAKE_VERSION"] = "mysql  Ver 8.4.3 for Linux"
        tool.run_sql(self.profile(ssl_mode="REQUIRED"), "select 1")
        self.assertIn("--ssl-mode=REQUIRED", self.h.calls()[-1]["args"])

    def test_stale_temp_files_are_swept(self):
        d = os.path.join(self.h.dir.name, "tmp")
        os.makedirs(d, mode=0o700, exist_ok=True)
        old = os.path.join(d, "old.cnf")
        fresh = os.path.join(d, "fresh.cnf")
        for f in (old, fresh):
            open(f, "w").close()
        os.utime(old, (time.time() - 7200, time.time() - 7200))
        tool.run_sql(self.profile(), "select 1")
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(fresh))

    def test_sigterm_removes_the_option_file(self):
        os.environ["FAKE_SLEEP"] = "20"
        env = dict(os.environ, DYNAMIA_MYSQL_HOME=self.h.dir.name)
        p = subprocess.Popen([sys.executable, os.path.join(BIN, "mysql-tool"), "query", "src", "select 1"], env=env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        d = os.path.join(self.h.dir.name, "tmp")
        for _ in range(100):
            if os.path.isdir(d) and os.listdir(d):
                break
            time.sleep(0.05)
        self.assertTrue(os.listdir(d), "option file never appeared")
        p.send_signal(signal.SIGTERM)
        p.wait(timeout=10)
        self.assertEqual(os.listdir(d), [])

    def test_clone_runs_in_the_background_but_early_errors_surface(self):
        os.environ["FAKE_SLEEP"] = "3"
        msg = tool.start_detached(self.profile(), "CLONE INSTANCE FROM 'c'@'h':3306 IDENTIFIED BY '@@ENV:REPL_PW@@'", wait=1)
        self.assertIn("background", msg)
        os.environ.pop("FAKE_SLEEP")
        os.environ["FAKE_FAIL"] = "ERROR 3869: clone failed s3cr3t-pw!"
        with self.assertRaises(tool.Fail) as cm:
            tool.start_detached(self.profile(), "CLONE INSTANCE FROM 'c'@'h':3306 IDENTIFIED BY '@@ENV:REPL_PW@@'", wait=5)
        self.assertNotIn("s3cr3t-pw!", str(cm.exception))
        os.environ.pop("FAKE_FAIL")


class PlannerHardeningTest(unittest.TestCase):
    def facts(self, **kw):
        return {"version": "8.4.3", "comment": "", "flavor": "mysql", "ver": (8, 4, 3), "supported": True, "data_bytes": kw.pop("data", 0),
                "vars": {"server_id": kw.pop("sid", "2"), "gtid_mode": kw.pop("gtid", "ON"), "log_bin": "ON", **kw}}

    def src(self):
        return self.facts(sid="1", server_uuid="aaaa", innodb_page_size="16384", version_compile_os="Linux", binlog_expire_logs_seconds="604800")

    def test_a_target_that_holds_data_is_blocked_unless_rebuild(self):
        rep = self.facts(data=5 * 1024 ** 3, server_uuid="bbbb", innodb_page_size="16384", version_compile_os="Linux")
        b = tool.blockers_for(self.src(), rep, "xtrabackup", {"verdict": "NONE", "replicas": 0, "read_only": "0"})
        self.assertTrue(any("REPLACES" in x for x in b) and any("looks like a primary" in x for x in b))
        self.assertEqual(tool.blockers_for(self.src(), rep, "xtrabackup", {"verdict": "NONE", "replicas": 0, "read_only": "0"}, rebuild=True), [])

    def test_a_target_with_its_own_replicas_is_always_blocked(self):
        rep = self.facts(server_uuid="bbbb", innodb_page_size="16384", version_compile_os="Linux")
        b = tool.blockers_for(self.src(), rep, "xtrabackup", {"verdict": "NONE", "replicas": 2, "read_only": "1"}, rebuild=True)
        self.assertTrue(any("replicate from the target" in x for x in b))

    def test_already_replicating_target_needs_rebuild(self):
        rep = self.facts(server_uuid="bbbb", innodb_page_size="16384", version_compile_os="Linux")
        st = {"verdict": "OK", "replicas": 0, "read_only": "1"}
        self.assertTrue(tool.blockers_for(self.src(), rep, "dump", st))
        self.assertEqual(tool.blockers_for(self.src(), rep, "dump", st, rebuild=True), [])

    def test_physical_and_gtid_prerequisites_on_the_replica(self):
        rep = self.facts(gtid="OFF", server_uuid="aaaa", innodb_page_size="8192", version_compile_os="Linux")
        text = " ".join(tool.blockers_for(self.src(), rep, "clone", {"verdict": "NONE", "replicas": 0, "read_only": "1"}))
        for needle in ("innodb_page_size differs", "server_uuid", "replica gtid_mode is OFF"):
            self.assertIn(needle, text)

    def test_runbook_steps_are_safe(self):
        rep = self.facts(server_uuid="bbbb")
        for m in ("xtrabackup", "clone", "dump"):
            text = tool.runbook(self.src(), rep, m, "src", "rep", ("db1:3306", "db2:3306"))
            self.assertIn("db1:3306", text)
            self.assertIn("NEW REPLICA = db2:3306", text)
            self.assertIn("read_only=ON", text)
            self.assertIn("binlog_expire_logs_seconds=604800", text)
            self.assertNotIn("move-back", text)
        text = tool.runbook(self.src(), rep, "xtrabackup", "src", "rep")
        self.assertIn("--copy-back", text)
        self.assertNotIn("systemctl stop <service> ;", text)
        self.assertRegex(text, r"stop the server:.*\n.*is-active")
        self.assertIn("auto.cnf", text)
        self.assertIn("mysql-tool backup src", text)


class FailoverHardeningTest(unittest.TestCase):
    def setUp(self):
        self.h = Home({**VER, "SHOW GLOBAL VARIABLES": "Variable_name\tValue\nlog_bin\tON\nlog_replica_updates\tON\n",
                       "SHOW REPLICA STATUS": "Source_Host\tReplica_IO_Running\tReplica_SQL_Running\tSeconds_Behind_Source\tAuto_Position\tRetrieved_Gtid_Set\n"
                                              "old\tYes\tYes\t0\t1\taaaa-1111:1-9\n",
                       "GTID_SUBTRACT": "m\n\n", "@@GLOBAL.gtid_executed": "g\naaaa-1111:1-10\n"})

    def tearDown(self):
        os.environ.pop("FAKE_FAIL", None)
        self.h.close()

    def test_unknown_or_unreachable_old_source_is_not_assumed_down(self):
        with self.assertRaises(tool.Fail):
            tool.plan_failover("rep", "typo", [])
        os.environ["FAKE_FAIL"] = "ERROR 2003: cannot connect"
        with self.assertRaises(tool.Fail):
            tool.plan_failover("rep", "src", [])

    def test_neither_old_source_nor_down_flag_is_an_error(self):
        with self.assertRaises(tool.Fail):
            tool.plan_failover("rep", None, [])

    def test_source_down_flag_is_refused_when_it_answers(self):
        with self.assertRaises(tool.Fail):
            tool.plan_failover("rep", "src", [], source_down=True)

    def test_switchover_plan_waits_for_relay_logs_and_catch_up(self):
        text, ok = tool.plan_failover("rep", "src", [])
        self.assertTrue(ok)
        self.assertIn("WAIT_FOR_EXECUTED_GTID_SET('aaaa-1111:1-9'", text)
        self.assertIn("my.cnf", text)
        self.assertLess(text.index("read_only=ON"), text.index("STOP REPLICA"))

    def test_failover_plan_starts_with_fencing(self):
        text, ok = tool.plan_failover("rep", None, [], source_down=True)
        self.assertTrue(ok)
        self.assertRegex(text, r"1\. FENCE")

    def test_a_more_advanced_other_replica_blocks_the_promotion(self):
        self.h.close()
        self.h = Home({**VER, "SHOW GLOBAL VARIABLES": "Variable_name\tValue\nlog_bin\tON\n",
                       "SHOW REPLICA STATUS": "Source_Host\tReplica_IO_Running\tReplica_SQL_Running\tSeconds_Behind_Source\tAuto_Position\n"
                                              "old\tYes\tYes\t0\t1\n",
                       "GTID_SUBTRACT": "m\nbbbb-2222:1-3\n", "@@GLOBAL.gtid_executed": "g\naaaa-1111:1-10\n"})
        text, ok = tool.plan_failover("rep", None, ["src"], source_down=True)
        self.assertFalse(ok)
        self.assertIn("promote src instead", text)


class StatusAndMiscTest(unittest.TestCase):
    def tearDown(self):
        self.h.close()

    def test_every_channel_is_checked(self):
        head = "Channel_Name\tSource_Host\tReplica_IO_Running\tReplica_SQL_Running\tSeconds_Behind_Source\tLast_SQL_Error\tAuto_Position"
        self.h = Home({"SHOW REPLICA STATUS": head + "\n\th1\tYes\tYes\t0\t\t1\nsecond\th2\tYes\tNo\tNULL\tboom\t1\n"})
        r = tool.replica_status(tool.get_profile("rep"))
        self.assertEqual(r["verdict"], "BROKEN")
        self.assertTrue(any("channel 'second'" in p for p in r["problems"]))

    def test_mariadb_diagnose_says_the_errant_check_was_not_done(self):
        head = "Master_Host\tSlave_IO_Running\tSlave_SQL_Running\tSeconds_Behind_Master\tLast_SQL_Errno\tLast_SQL_Error\tUsing_Gtid"
        self.h = Home({"SHOW REPLICA STATUS": head + "\nh\tYes\tNo\tNULL\t1032\tRow not found\tSlave_Pos\n",
                       "VERSION\\(\\)": "v\tc\n11.4.2-MariaDB\tmariadb.org binary\n", "gtid_current_pos": "g\n0-1-9\n"})
        v, lines = tool.diagnose(tool.get_profile("rep"), tool.get_profile("src"))
        self.assertEqual(v, "DIVERGED")
        text = " ".join(lines)
        self.assertIn("not available on MariaDB", text)
        self.assertNotIn("No errant GTIDs found", text)

    def test_monitor_survives_an_unknown_profile(self):
        self.h = Home()
        ok, line = tool.monitor_one("nope")
        self.assertEqual((ok, line.split(":")[0]), (False, "DOWN nope"))

    def test_scan_secrets_ignores_uppercase_port_flag(self):
        self.h = Home()
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "h"), "w") as fh:
                fh.write("mysql -P3306 -h db1 -e 'select 1'\nmysql -psecret1 db\n")
            hits, _ = tool.scan_secrets([d])
        self.assertEqual([n for _, n, _ in hits], [2])

    def test_physical_backup_refuses_when_the_datadir_is_not_local(self):
        self.h = Home({**VER, "SHOW GLOBAL VARIABLES": "Variable_name\tValue\ndatadir\t/definitely/not/here/\n"})
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(tool.Fail) as cm:
                tool.run_backup("src", "xtrabackup", os.path.join(d, "b"))
        self.assertIn("database host", str(cm.exception))

    def test_backup_folder_is_private_and_mariadb_file_names_verify(self):
        with tempfile.TemporaryDirectory() as d:
            self.h = Home({**VER, "SHOW GLOBAL VARIABLES": "Variable_name\tValue\ndatadir\t%s\n" % d})
            os.environ["PATH"] = os.path.join(HERE, "fakebin") + os.pathsep + os.environ["PATH"]
            try:
                target = os.path.join(d, "b")
                os.makedirs(target, mode=0o755)
                tool.run_backup("src", "dump", target)
                self.assertEqual(oct(os.stat(target).st_mode & 0o777), "0o700")
                t2 = os.path.join(d, "m")
                tool.run_backup("src", "xtrabackup", t2)
                os.rename(os.path.join(t2, "xtrabackup_checkpoints"), os.path.join(t2, "mariadb_backup_checkpoints"))
                os.rename(os.path.join(t2, "xtrabackup_binlog_info"), os.path.join(t2, "mariadb_backup_binlog_info"))
                self.assertEqual(tool.verify_backup(t2)[0], [])
            finally:
                os.environ["PATH"] = os.environ["PATH"].split(os.pathsep, 1)[1]


if __name__ == "__main__":
    unittest.main()


class FreshStatsTest(unittest.TestCase):
    def test_sizes_are_read_fresh_on_mysql_but_not_on_mariadb(self):
        h = Home({"VERSION\\(\\)": "v\tc\n8.4.3\tMySQL Community Server\n", "SUM\\(data_length": "b\n10000\n"})
        try:
            tool.facts(tool.get_profile("src"))
            self.assertIn("information_schema_stats_expiry=0", h.calls()[-1]["sql"])
        finally:
            h.close()
        h = Home({"VERSION\\(\\)": "v\tc\n11.4.2-MariaDB\tmariadb.org\n", "SUM\\(data_length": "b\n10000\n"})
        try:
            tool.facts(tool.get_profile("src"))
            self.assertNotIn("information_schema_stats_expiry", h.calls()[-1]["sql"])
        finally:
            h.close()


class AccountNoiseTest(unittest.TestCase):
    def test_builtin_accounts_and_mariadb_native_password_are_not_reported(self):
        rs = [{"User": "mysql.session", "Host": "localhost", "Super_priv": "Y", "Shutdown_priv": "Y"},
              {"User": "mariadb.sys", "Host": "localhost", "plugin": "mysql_native_password"},
              {"User": "app", "Host": "localhost", "plugin": "mysql_native_password"}]
        self.assertEqual(tool.audit_accounts(rs, "mariadb"), [])
        self.assertEqual(len(tool.audit_accounts(rs, "mysql")), 1)


class TlsAndSpaceTest(unittest.TestCase):
    def maria(self, **kw):
        return {"version": "11.4.2", "comment": "", "flavor": "mariadb", "ver": (11, 4, 2), "supported": True, "data_bytes": kw.pop("data", 0),
                "vars": {"server_id": kw.pop("sid", "1"), "log_bin": "ON", **kw}}

    def test_mariadb_without_tls_needs_an_explicit_flag(self):
        src, rep = self.maria(have_ssl="DISABLED"), self.maria(sid="2")
        self.assertTrue(any("TLS is not enabled" in x for x in tool.blockers_for(src, rep, "mariabackup")))
        self.assertEqual(tool.blockers_for(src, rep, "mariabackup", allow_plaintext=True), [])
        self.assertEqual(tool.blockers_for(self.maria(have_ssl="YES"), rep, "mariabackup"), [])

    def test_runbook_drops_ssl_options_when_tls_is_off(self):
        src, rep = self.maria(have_ssl="DISABLED"), self.maria(sid="2")
        off = tool.runbook(src, rep, "mariabackup", "s", "r", tls=False)
        on = tool.runbook(src, rep, "mariabackup", "s", "r", tls=True)
        self.assertNotIn("MASTER_SSL", off)
        self.assertNotIn("REQUIRE SSL", off)
        self.assertIn("MASTER_SSL=1", on)
        self.assertIn("REQUIRE SSL", on)


class GtidValueTest(unittest.TestCase):
    def test_positions_must_look_like_gtids(self):
        for bad in ("SET GLOBAL gtid_slave_pos=''", "SET GLOBAL gtid_slave_pos='abc'", "SET GLOBAL gtid_purged=''",
                    "SET GLOBAL gtid_purged='nothing'", "SET GLOBAL gtid_slave_pos='0-21-12'; SET GLOBAL gtid_slave_pos=''"):
            with self.assertRaises(tool.Fail, msg=bad):
                tool.check_write(bad)
        for good in ("SET GLOBAL gtid_slave_pos='0-21-12'", "SET GLOBAL gtid_slave_pos='0-21-12,1-5-7'",
                     "SET GLOBAL gtid_purged='3679ff8a-d0bb-11f1-b355-bc241173fbeb:1-17'",
                     "SET GLOBAL gtid_purged='+3679ff8a-d0bb-11f1-b355-bc241173fbeb:1-17:20-30'"):
            tool.check_write(good)


class CloneRestartTest(unittest.TestCase):
    def test_error_3707_is_reported_as_a_finished_clone(self):
        h = Home()
        try:
            os.environ["FAKE_FAIL"] = "ERROR 3707 (HY000): Restart server failed (mysqld is not managed by supervisor process)."
            msg = tool.start_detached(tool.get_profile("src"), "CLONE INSTANCE FROM 'c'@'h':3306 IDENTIFIED BY '@@ENV:REPL_PW@@'", wait=5)
            self.assertIn("copied the data", msg)
        finally:
            os.environ.pop("FAKE_FAIL", None)
            h.close()


class FailoverDeadSourceTest(unittest.TestCase):
    def test_a_dead_source_is_not_a_blocker_but_a_broken_sql_thread_is(self):
        cand = {"vars": {"log_bin": "ON", "log_replica_updates": "ON"}}
        io_down = {"verdict": "BROKEN", "io": "Connecting", "sql": "Yes", "problems": ["IO thread is Connecting"], "_raw": {}}
        self.assertEqual(tool.failover_blockers(cand, io_down, source_down=True), [])
        self.assertEqual(len(tool.failover_blockers(cand, io_down, source_down=False)), 1)
        sql_down = {"verdict": "BROKEN", "io": "Yes", "sql": "No", "problems": ["SQL thread is No"], "_raw": {"Last_SQL_Error": "boom"}}
        self.assertEqual(len(tool.failover_blockers(cand, sql_down, source_down=True)), 1)


class WritableReplicaTest(unittest.TestCase):
    def test_a_writable_replica_is_a_warning(self):
        head = "Source_Host\tReplica_IO_Running\tReplica_SQL_Running\tSeconds_Behind_Source\tAuto_Position"
        h = Home({"@@max_connections": "v\tc\tmc\tro\n8.4.3\tMySQL\t100\t0\n", "SHOW GLOBAL STATUS": "Variable_name\tValue\nUptime\t10\nThreads_connected\t1\n",
                  "REPLICA STATUS": head + "\nh\tYes\tYes\t0\t1\n"})
        try:
            ok, line = tool.monitor_one("src")
            self.assertFalse(ok)
            self.assertIn("writable", line)
        finally:
            h.close()
