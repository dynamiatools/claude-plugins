import os
import unittest

from _env import Home, load

tool = load("mysql-tool")


class SqlChecksTest(unittest.TestCase):
    def test_readonly_accepts_selects(self):
        for s in ("SELECT 1", "show variables like 'x'", "DESCRIBE t", "EXPLAIN SELECT * FROM t",
                  "WITH a AS (SELECT 1) SELECT * FROM a", "select 'a;b'"):
            tool.check_readonly(s)

    def test_readonly_rejects_everything_else(self):
        for s in ("DELETE FROM t", "SELECT 1; DROP TABLE t", "SELECT * INTO OUTFILE '/tmp/x' FROM t",
                  "SELECT * FROM t FOR UPDATE", "EXPLAIN ANALYZE DELETE FROM t", "SELECT SLEEP(5)",
                  "WITH a AS (SELECT 1) DELETE FROM t", "SET GLOBAL read_only=1", "SELECT 1 /* x */; SELECT 2"):
            with self.assertRaises(tool.Fail, msg=s):
                tool.check_readonly(s)

    def test_write_allowlist(self):
        ok = ["CREATE USER 'repl'@'10.0.0.2' IDENTIFIED BY '@@ENV:REPL_PW@@'",
              "GRANT REPLICATION SLAVE ON *.* TO 'repl'@'10.0.0.2'",
              "CHANGE REPLICATION SOURCE TO SOURCE_HOST='h', SOURCE_PASSWORD='@@ENV:REPL_PW@@', SOURCE_AUTO_POSITION=1",
              "START REPLICA; STOP REPLICA", "SET GLOBAL gtid_purged='uuid:1-5'"]
        for s in ok:
            tool.check_write(s)

    def test_write_refuses_destructive_and_literal_passwords(self):
        bad = ["DROP DATABASE x", "DELETE FROM t WHERE id=1", "RESET BINARY LOGS AND GTIDS", "RESET REPLICA ALL",
               "PURGE BINARY LOGS TO 'x'", "TRUNCATE t", "GRANT ALL ON *.* TO 'a'@'%'",
               "CREATE USER 'r'@'h' IDENTIFIED BY 'plain'",
               "CHANGE REPLICATION SOURCE TO SOURCE_PASSWORD='plain'", "START REPLICA; DROP TABLE t"]
        for s in bad:
            with self.assertRaises(tool.Fail, msg=s):
                tool.check_write(s)

    def test_drop_inside_a_string_does_not_confuse_the_splitter(self):
        self.assertEqual(len(tool.split_statements("SELECT 'a;b'; SELECT \"c;d\"")), 2)


class VersionTest(unittest.TestCase):
    def test_flavor_and_baseline(self):
        self.assertEqual(tool.flavor_of("8.4.3", "Percona Server (GPL)"), "percona")
        self.assertEqual(tool.flavor_of("11.4.2-MariaDB", ""), "mariadb")
        self.assertEqual(tool.flavor_of("8.4.0", "MySQL Community Server"), "mysql")
        self.assertTrue(tool.supported("mysql", (8, 4, 0)))
        self.assertFalse(tool.supported("mysql", (8, 0, 36)))
        self.assertTrue(tool.supported("mariadb", (10, 11, 6)))
        self.assertFalse(tool.supported("mariadb", (10, 6, 1)))


class ClientSecurityTest(unittest.TestCase):
    def setUp(self):
        self.h = Home({"select 1": "a\n1\n"})

    def tearDown(self):
        self.h.close()

    def test_password_goes_in_a_0600_option_file_never_argv(self):
        prof = tool.get_profile("src")
        tool.run_sql(prof, "select 1")
        call = self.h.calls()[0]
        self.assertNotIn("s3cr3t-pw!", " ".join(call["args"]))
        self.assertEqual(call["cnf"]["mode"], 0o600)
        self.assertIn("s3cr3t-pw!", call["cnf"]["text"])
        self.assertTrue(call["args"][0].startswith("--defaults-extra-file="))
        self.assertIn("--init-command=SET SESSION TRANSACTION READ ONLY", call["args"])
        left = os.listdir(os.path.join(self.h.dir.name, "tmp"))
        self.assertEqual(left, [])

    def test_output_and_errors_are_redacted(self):
        self.h.close()
        self.h = Home({"select": "x\ns3cr3t-pw! was here\n"})
        out = tool.run_sql(tool.get_profile("src"), "select 1")
        self.assertNotIn("s3cr3t-pw!", out)
        os.environ["FAKE_FAIL"] = "Access denied; using password s3cr3t-pw!"
        with self.assertRaises(tool.Fail) as cm:
            tool.run_sql(tool.get_profile("src"), "select 1")
        self.assertNotIn("s3cr3t-pw!", str(cm.exception))

    def test_placeholder_is_escaped_and_sent_over_stdin(self):
        tool.run_sql(tool.get_profile("src"), "CREATE USER 'r'@'h' IDENTIFIED BY '@@ENV:REPL_PW@@'", readonly=False)
        call = self.h.calls()[0]
        self.assertIn("repl''pw\\\\x", call["sql"])
        self.assertNotIn("repl'pw", " ".join(call["args"]))
        self.assertNotIn("--init-command=SET SESSION TRANSACTION READ ONLY", call["args"])

    def test_missing_secret_is_an_error(self):
        with self.assertRaises(tool.Fail):
            tool.fill_placeholders("'@@ENV:NOPE@@'")

    def test_loose_secrets_file_is_refused(self):
        self.h.close()
        self.h = Home(mode=0o644)
        with self.assertRaises(tool.Fail):
            tool.load_secrets()

    def test_profile_with_a_password_is_refused(self):
        with open(os.path.join(self.h.dir.name, "profiles.toml"), "w") as fh:
            fh.write('[profiles.x]\nuser="a"\npassword="p"\n')
        with self.assertRaises(tool.Fail):
            tool.load_profiles()

    def test_secret_gen_never_prints_and_does_not_overwrite(self):
        tool.store_secret("NEW_PW", "abc12345")
        with self.assertRaises(tool.Fail):
            tool.store_secret("NEW_PW", "other")
        self.assertEqual(tool.main(["secret-gen", "GEN_PW"]), 0)
        self.assertGreaterEqual(len(tool.load_secrets()["GEN_PW"]), 16)
        self.assertEqual(oct(os.stat(tool.secrets_path()).st_mode & 0o777), "0o600")

    def test_redact_scrubs_sql_passwords(self):
        t = tool.redact("CHANGE REPLICATION SOURCE TO SOURCE_PASSWORD='hunter2', X=1; ... IDENTIFIED BY 'abc'")
        self.assertNotIn("hunter2", t)
        self.assertNotIn("abc", t)


class ReplicaStatusTest(unittest.TestCase):
    def tearDown(self):
        self.h.close()

    def status(self, header, row, **kw):
        self.h = Home({"show replica status": header + "\n" + row + "\n"})
        return tool.replica_status(tool.get_profile("rep"), **kw)

    def test_mysql_84_ok(self):
        h = "Source_Host\tReplica_IO_Running\tReplica_SQL_Running\tSeconds_Behind_Source\tLast_IO_Error\tLast_SQL_Error\tAuto_Position"
        r = self.status(h, "10.0.0.1\tYes\tYes\t2\t\t\t1")
        self.assertEqual((r["verdict"], r["problems"]), ("OK", []))

    def test_mariadb_names_and_broken(self):
        h = "Master_Host\tSlave_IO_Running\tSlave_SQL_Running\tSeconds_Behind_Master\tLast_Error\tUsing_Gtid"
        r = self.status(h, "10.0.0.1\tYes\tNo\tNULL\tDuplicate entry\tSlave_Pos")
        self.assertEqual(r["verdict"], "BROKEN")
        self.assertTrue(any("Duplicate entry" in p for p in r["problems"]))

    def test_lagging_and_no_gtid(self):
        h = "Source_Host\tReplica_IO_Running\tReplica_SQL_Running\tSeconds_Behind_Source\tAuto_Position"
        r = self.status(h, "h\tYes\tYes\t500\t0", max_lag=30)
        self.assertEqual(r["verdict"], "LAGGING")
        self.assertEqual(len(r["problems"]), 2)

    def test_not_a_replica(self):
        self.h = Home({"show replica status": ""})
        self.assertEqual(tool.replica_status(tool.get_profile("rep"))["verdict"], "NONE")


class PlannerTest(unittest.TestCase):
    def facts(self, flavor="mysql", ver="8.4.3", sid="1", gtid="ON", binlog="ON"):
        v = tool.parse_version(ver)
        return {"version": ver, "comment": "", "flavor": flavor, "ver": v, "supported": tool.supported(flavor, v),
                "data_bytes": 5 * 1024 ** 3, "vars": {"server_id": sid, "gtid_mode": gtid, "log_bin": binlog}}

    def test_clean_plan_has_confirm_steps_and_no_secrets(self):
        s, r = self.facts(), self.facts(sid="2")
        self.assertEqual(tool.blockers_for(s, r, "xtrabackup"), [])
        text = tool.runbook(s, r, "xtrabackup", "src", "rep")
        self.assertIn("SOURCE_AUTO_POSITION=1", text)
        self.assertIn("[CONFIRM]", text)
        self.assertIn("@@ENV:REPL_PW@@", text)
        self.assertNotIn("--password", text)
        self.assertNotIn("RESET BINARY LOGS AND GTIDS\"", text)

    def test_mariadb_runbook_uses_gtid_slave_pos(self):
        s, r = self.facts("mariadb", "11.4.2"), self.facts("mariadb", "11.4.2", sid="2")
        text = tool.runbook(s, r, "mariabackup", "src", "rep")
        self.assertIn("MASTER_USE_GTID=slave_pos", text)
        self.assertIn("gtid_slave_pos", text)
        self.assertIn("mariadb-backup", text)

    def test_blockers(self):
        b = tool.blockers_for(self.facts(), self.facts("mariadb", "11.4.2", sid="1"), "xtrabackup")
        self.assertTrue(any("cannot replicate" in x for x in b))
        self.assertTrue(any("server_id" in x for x in b))
        b = tool.blockers_for(self.facts(gtid="OFF", binlog="OFF"), self.facts(sid="2"), "xtrabackup")
        self.assertTrue(any("binary log" in x for x in b) and any("gtid_mode" in x for x in b))
        b = tool.blockers_for(self.facts("mariadb", "11.4.2"), self.facts("mariadb", "11.4.2", sid="2"), "clone")
        self.assertTrue(any("not available" in x for x in b))
        b = tool.blockers_for(self.facts(ver="8.0.36"), self.facts(ver="8.4.3", sid="2"), "dump")
        self.assertTrue(any("baseline" in x for x in b))


if __name__ == "__main__":
    unittest.main()
