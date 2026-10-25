import json
import os
import tempfile
import unittest

from _env import Home, HERE, load

tool = load("mysql-tool")
FAKEBIN = os.path.join(HERE, "fakebin")
VER = {"VERSION\\(\\)": "v\tc\n8.4.3\tMySQL Community Server\n",
       "SUM\\(data_length": "b\n10000\n"}


class AuditTest(unittest.TestCase):
    def test_risky_config(self):
        v = {"sync_binlog": "0", "innodb_flush_log_at_trx_commit": "2", "log_bin": "ON", "binlog_format": "MIXED", "gtid_mode": "OFF",
             "enforce_gtid_consistency": "OFF", "sql_mode": "NO_ENGINE_SUBSTITUTION", "local_infile": "ON",
             "binlog_expire_logs_seconds": "0", "expire_logs_days": "0"}
        text = " ".join(t for _, t in tool.audit_config("mysql", v))
        for needle in ("sync_binlog=0", "innodb_flush_log_at_trx_commit=2", "binlog_format=MIXED", "gtid_mode=OFF", "no strict mode",
                       "local_infile", "never purged"):
            self.assertIn(needle, text)

    def test_safe_config_has_no_warnings(self):
        v = {"sync_binlog": "1", "innodb_flush_log_at_trx_commit": "1", "log_bin": "ON", "binlog_format": "ROW", "gtid_mode": "ON",
             "enforce_gtid_consistency": "ON", "sql_mode": "STRICT_TRANS_TABLES", "binlog_expire_logs_seconds": "604800",
             "character_set_server": "utf8mb4", "local_infile": "OFF", "skip_name_resolve": "ON", "innodb_buffer_pool_size": "8589934592"}
        self.assertEqual([x for x in tool.audit_config("mysql", v) if x[0] == "warn"], [])

    def test_mariadb_has_no_mysql_gtid_findings(self):
        res = tool.audit_config("mariadb", {"log_bin": "ON", "gtid_strict_mode": "ON"})
        self.assertFalse(any("gtid_mode" in t for _, t in res))

    def test_accounts(self):
        rs = [{"User": "", "Host": "localhost"}, {"User": "app", "Host": "%", "ssl_type": "", "Super_priv": "Y", "plugin": "mysql_native_password"},
              {"User": "root", "Host": "localhost", "Super_priv": "Y", "ssl_type": ""}]
        text = " ".join(t for _, t in tool.audit_accounts(rs))
        for needle in ("anonymous", "any host", "SUPER", "does not require TLS", "mysql_native_password"):
            self.assertIn(needle, text)
        self.assertNotIn("'root'@'localhost'", text)

    def test_account_query_never_selects_hashes(self):
        h = Home({"information_schema.columns": "column_name\nUser\nHost\nplugin\nauthentication_string\nPassword\nSuper_priv\n"})
        try:
            tool.account_rows(tool.get_profile("src"))
            sql = h.calls()[-1]["sql"]
            self.assertNotIn("authentication_string", sql)
            self.assertNotIn("Password", sql)
            self.assertIn("Super_priv", sql)
        finally:
            h.close()


class ScanSecretsTest(unittest.TestCase):
    def test_finds_and_never_prints_values(self):
        with tempfile.TemporaryDirectory() as d:
            for name, text in {"a.cnf": "[client]\npassword = hunter2\n", "h": "mysql -u root -pSecret1 db\nls\n",
                               "s.sql": "CREATE USER 'a'@'h' IDENTIFIED BY 'plainpw';\nCHANGE REPLICATION SOURCE TO SOURCE_PASSWORD='x1';\n",
                               "ok.sql": "CREATE USER 'a'@'h' IDENTIFIED BY '@@ENV:REPL_PW@@';\n"}.items():
                with open(os.path.join(d, name), "w") as fh:
                    fh.write(text)
            os.environ["DYNAMIA_MYSQL_HOME"] = d
            hits, _ = tool.scan_secrets([d])
        found = {(os.path.basename(p), n) for p, n, _ in hits}
        self.assertEqual(found, {("a.cnf", 2), ("h", 1), ("s.sql", 1), ("s.sql", 2)})
        self.assertFalse(any("hunter2" in k or "plainpw" in k for _, _, k in hits))


class PerformanceTest(unittest.TestCase):
    def tearDown(self):
        self.h.close()

    def test_digest_flags(self):
        self.h = Home({"@@performance_schema": "p\n1\n", "events_statements_summary_by_digest":
                       "db\tquery\tcalls\ttotal_s\tavg_s\texamined\tsent\tno_index\nshop\tSELECT ?\t10\t5.0\t0.5\t100000\t10\t3\n"})
        r = tool.slow_queries(tool.get_profile("src"))[0]
        self.assertIn("without a usable index", r["flags"])
        self.assertIn("10000x more rows", r["flags"])

    def test_performance_schema_off_is_explained(self):
        self.h = Home({"@@performance_schema": "p\n0\n"})
        with self.assertRaises(tool.Fail):
            tool.slow_queries(tool.get_profile("src"))

    def test_deadlock_section_is_extracted(self):
        status = "Type\tName\tStatus\nInnoDB\t\t=====\\n------------------------\\nLATEST DETECTED DEADLOCK\\n------------------------\\n*** (1) TRANSACTION: x\\n--------\\nTRANSACTIONS\\n--------\\nmore"
        self.h = Home({"innodb_trx": "trx_id\n", "innodb_lock_waits": "waiting_pid\n", "INNODB STATUS": status})
        res = tool.locks(tool.get_profile("src"), "mysql")
        self.assertIn("TRANSACTION: x", res["deadlock"])
        self.assertNotIn("TRANSACTIONS", res["deadlock"])


class SchemaDiffTest(unittest.TestCase):
    def test_diff(self):
        a = {"tables": {"s.t": "InnoDB", "s.only_a": "InnoDB"}, "columns": {"s.t.id": "int null=NO", "s.t.x": "int null=YES"},
             "indexes": {"s.t#PRIMARY": "(id) unique"}}
        b = {"tables": {"s.t": "InnoDB", "s.only_b": "InnoDB"}, "columns": {"s.t.id": "bigint null=NO"},
             "indexes": {"s.t#PRIMARY": "(id) unique", "s.t#ix": "(x) "}}
        text = "\n".join(tool.schema_diff(a, b, "A", "B"))
        for needle in ("only in A, table: s.only_a", "only in B, table: s.only_b", "only in A, column: s.t.x", "differs, column s.t.id", "only in B, index: s.t#ix"):
            self.assertIn(needle, text)
        self.assertEqual(tool.schema_diff(a, a), [])


class UpgradeTest(unittest.TestCase):
    def test_80_to_84_findings(self):
        res = tool.upgrade_findings("mysql", (8, 0, 36), ["expire_logs_days"], 3, 1)
        text = " ".join(t for _, t in res)
        for needle in ("expire_logs_days", "3 account(s)", "spatial", "upgrade checker"):
            self.assertIn(needle, text)

    def test_other_sources(self):
        self.assertIn("Already on", tool.upgrade_findings("mysql", (8, 4, 3), [], 0, 0)[0][1])
        self.assertIn("not an upgrade source", tool.upgrade_findings("mysql", (5, 7, 44), [], 0, 0)[0][1])
        self.assertIn("No verified rule list", tool.upgrade_findings("mariadb", (10, 11, 6), [], 0, 0)[0][1])


class MonitorTest(unittest.TestCase):
    def tearDown(self):
        self.h.close()

    def test_ok_warn_and_down(self):
        self.h = Home({"@@max_connections": "v\tc\tmc\tro\n8.4.3\tMySQL Community Server\t100\t0\n",
                       "SHOW GLOBAL STATUS": "Variable_name\tValue\nUptime\t172800\nThreads_connected\t95\n", "REPLICA STATUS": ""})
        ok, line = tool.monitor_one("src")
        self.assertFalse(ok)
        self.assertIn("connections at 95%", line)
        os.environ["FAKE_FAIL"] = "ERROR 2003: Can't connect"
        ok, line = tool.monitor_one("src")
        self.assertEqual((ok, line.split(":")[0]), (False, "DOWN src"))


class DiagnoseTest(unittest.TestCase):
    h = None

    def tearDown(self):
        if self.h:
            self.h.close()

    def broken(self, io_no="0", sql_no="0", io="Yes", sql="No", err="boom"):
        head = "Source_Host\tReplica_IO_Running\tReplica_SQL_Running\tSeconds_Behind_Source\tLast_IO_Errno\tLast_SQL_Errno\tLast_IO_Error\tLast_SQL_Error\tAuto_Position"
        return head + "\n" + "h\t%s\t%s\tNULL\t%s\t%s\t%s\t\t1\n" % (io, sql, io_no, sql_no, err if io_no != "0" else "")

    def test_purged_logs_mean_rebuild(self):
        self.h = Home({"SHOW REPLICA STATUS": self.broken(io_no="1236", io="No", err="Got fatal error 1236 purged binary logs")})
        v, _ = tool.diagnose(tool.get_profile("rep"), tool.get_profile("src"))
        self.assertEqual(v, "REBUILD")

    def test_connection(self):
        self.h = Home({"SHOW REPLICA STATUS": self.broken(io_no="2003", io="Connecting", err="Can't connect")})
        self.assertEqual(tool.diagnose(tool.get_profile("rep"), tool.get_profile("src"))[0], "CONNECTION")

    def test_errant_gtids(self):
        head = self.broken(sql_no="1062").replace("\t\t1\n", "\tDuplicate entry\t1\n")
        self.h = Home({"SHOW REPLICA STATUS": head, "GTID_SUBTRACT": "e\nbbbb-2222:1-3\n", "VERSION\\(\\)": "v\tc\n8.4.3\tMySQL\n",
                       "@@GLOBAL.gtid_executed": "g\naaaa-1111:1-10\n"})
        v, lines = tool.diagnose(tool.get_profile("rep"), tool.get_profile("src"))
        self.assertEqual(v, "ERRANT")
        self.assertIn("bbbb-2222:1-3", " ".join(lines))

    def test_diverged_without_errant(self):
        head = self.broken(sql_no="1032").replace("\t\t1\n", "\tRow not found\t1\n")
        self.h = Home({"SHOW REPLICA STATUS": head, "GTID_SUBTRACT": "e\n\n", "VERSION\\(\\)": "v\tc\n8.4.3\tMySQL\n",
                       "@@GLOBAL.gtid_executed": "g\naaaa-1111:1-10\n"})
        self.assertEqual(tool.diagnose(tool.get_profile("rep"), tool.get_profile("src"))[0], "DIVERGED")

    def test_gtid_text_is_validated(self):
        with self.assertRaises(tool.Fail):
            tool.clean_gtid("uuid:1'; DROP TABLE x; --")


class FailoverTest(unittest.TestCase):
    def cand(self, **v):
        return {"vars": {"log_bin": "ON", "log_replica_updates": "ON", **v}}

    def test_blockers(self):
        ok = {"verdict": "OK", "problems": []}
        self.assertEqual(tool.failover_blockers(self.cand(), ok, "g", "g", "", True, "mysql"), [])
        b = tool.failover_blockers(self.cand(log_bin="OFF"), {"verdict": "NONE", "problems": []}, "g", "g", "uuid:1-5", True, "mysql")
        self.assertEqual(len(b), 3)
        b = tool.failover_blockers(self.cand(), ok, "0-1-10", "0-1-9", "", True, "mariadb")
        self.assertIn("differs", b[0])
        self.assertEqual(tool.failover_blockers(self.cand(), ok, "", "g", "", False, "mysql"), [])

    def test_runbook_keeps_destructive_steps_manual(self):
        for alive in (True, False):
            text = tool.failover_runbook("mysql", alive, "cand", ["rep2"])
            self.assertIn("the user runs by hand", text)
            self.assertNotIn("mysql-tool exec cand \"RESET", text)
            self.assertIn("[CONFIRM]", text)
        self.assertIn("DOWN", tool.failover_runbook("mysql", False, "cand", []))
        self.assertIn("MASTER_USE_GTID=slave_pos", tool.failover_runbook("mariadb", True, "cand", ["r"]))
        with self.assertRaises(tool.Fail):
            tool.check_write("RESET REPLICA ALL")


class BackupTest(unittest.TestCase):
    def setUp(self):
        self.old_path = os.environ["PATH"]
        os.environ["PATH"] = FAKEBIN + os.pathsep + self.old_path
        self.h = Home({**VER, "SHOW GLOBAL VARIABLES": "Variable_name\tValue\nserver_id\t1\n"})
        self.work = tempfile.TemporaryDirectory()

    def tearDown(self):
        os.environ["PATH"] = self.old_path
        self.h.close()
        self.work.cleanup()

    def test_physical_backup_and_verify(self):
        target = os.path.join(self.work.name, "b1")
        msg = tool.run_backup("src", "xtrabackup", target)
        self.assertIn("backup finished", msg)
        problems, man = tool.verify_backup(target)
        self.assertEqual(problems, [])
        self.assertEqual(oct(os.stat(os.path.join(target, "backup-manifest.json")).st_mode & 0o777), "0o600")
        os.unlink(os.path.join(target, "xtrabackup_binlog_info"))
        self.assertTrue(any("binlog_info" in p for p in tool.verify_backup(target)[0]))
        self.assertEqual(os.listdir(os.path.join(self.h.dir.name, "tmp")), [])

    def test_dump_backup_detects_tampering_and_truncation(self):
        target = os.path.join(self.work.name, "b2")
        tool.run_backup("src", "dump", target)
        self.assertEqual(tool.verify_backup(target)[0], [])
        dump = os.path.join(target, "dump.sql")
        with open(dump, "a") as fh:
            fh.write("-- edited\n")
        self.assertTrue(any("sha256" in p for p in tool.verify_backup(target)[0]))
        with open(dump, "w") as fh:
            fh.write("CREATE TABLE t (id int);\n")
        self.assertTrue(any("truncated" in p for p in tool.verify_backup(target)[0]))

    def test_refuses_nonempty_target_wrong_method_and_dry_run_writes_nothing(self):
        target = os.path.join(self.work.name, "b3")
        os.makedirs(target)
        open(os.path.join(target, "x"), "w").close()
        with self.assertRaises(tool.Fail):
            tool.run_backup("src", "dump", target)
        with self.assertRaises(tool.Fail):
            tool.run_backup("src", "mariabackup", os.path.join(self.work.name, "b4"))
        fresh = os.path.join(self.work.name, "b5")
        self.assertIn("dry run", tool.run_backup("src", "dump", fresh, dry_run=True))
        self.assertFalse(os.path.exists(fresh))

    def test_not_enough_space_is_refused(self):
        self.h.close()
        self.h = Home({**VER, "SUM\\(data_length": "b\n%d\n" % (10 ** 18), "SHOW GLOBAL VARIABLES": "Variable_name\tValue\n"})
        with self.assertRaises(tool.Fail):
            tool.run_backup("src", "dump", os.path.join(self.work.name, "b6"))

    def test_missing_manifest(self):
        self.assertIn("manifest", tool.verify_backup(self.work.name)[0][0])


if __name__ == "__main__":
    unittest.main()
