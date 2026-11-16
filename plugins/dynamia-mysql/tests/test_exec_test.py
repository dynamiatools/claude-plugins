import json
import os
import subprocess
import sys
import tempfile
import unittest

from _env import HERE, Home, load

tool = load("mysql-tool")
GUARD = os.path.join(HERE, "..", "bin", "mysql-guard")
FAKE = os.path.join(HERE, "fake_client.py")


def add_profiles(home, text):
    with open(os.path.join(home.dir.name, "profiles.toml"), "a") as fh:
        fh.write(text)


def profile(name, extra):
    return '[profiles.%s]\nhost="127.0.0.1"\nuser="dba"\nsecret="PROD_PW"\nclient="%s"\n%s\n' % (name, FAKE, extra)


class ExecTestTool(unittest.TestCase):
    def setUp(self):
        self.h = Home()
        add_profiles(self.h, profile("dev", 'env="test"'))

    def tearDown(self):
        self.h.close()

    def run_tool(self, name, sql):
        return tool.main(["exec-test", name, sql])

    def test_runs_destructive_sql_on_a_test_profile_and_keeps_a_trail(self):
        for sql in ("DROP DATABASE IF EXISTS shop_test", "drop table a, b", "TRUNCATE TABLE shop.orders", "DELETE FROM t",
                    "delete from t where id > 3", "UPDATE t SET a = 1", "RESET BINARY LOGS AND GTIDS", "PURGE BINARY LOGS BEFORE '2026-01-01'"):
            with self.subTest(sql=sql):
                self.assertEqual(self.run_tool("dev", sql), 0)
        calls = self.h.calls()
        self.assertEqual(len(calls), 8)
        self.assertNotIn("--init-command=SET SESSION TRANSACTION READ ONLY", calls[0]["args"])
        trail = os.path.join(self.h.dir.name, "exec-test.log")
        self.assertEqual(oct(os.stat(trail).st_mode & 0o777), "0o600")
        with open(trail) as fh:
            self.assertIn("dev\tDROP DATABASE IF EXISTS shop_test", fh.read())

    def test_refuses_a_profile_that_is_not_marked_test(self):
        add_profiles(self.h, profile("qa", 'env="prod"'))
        for name in ("src", "qa"):
            self.assertNotEqual(self.run_tool(name, "DROP TABLE t"), 0, name)
        self.assertEqual(self.h.calls(), [])

    def test_refuses_system_schemas_stacked_statements_secrets_and_other_sql(self):
        for sql in ("DROP DATABASE mysql", "DROP TABLE sys.x", "TRUNCATE information_schema.tables", "DELETE FROM `mysql`.`user`",
                    "DROP TABLE t; DROP TABLE u", "DELETE FROM t WHERE a='@@ENV:PROD_PW@@'", "SELECT 1", "GRANT ALL ON *.* TO 'a'@'h'",
                    "ALTER TABLE t ADD c int", "source /tmp/x.sql", "DROP USER 'a'@'h'"):
            with self.subTest(sql=sql):
                self.assertNotEqual(self.run_tool("dev", sql), 0)
        self.assertEqual(self.h.calls(), [])

    def test_a_default_database_that_is_a_system_schema_is_refused(self):
        add_profiles(self.h, profile("sysdb", 'env="test"\ndatabase="mysql"'))
        self.assertNotEqual(self.run_tool("sysdb", "TRUNCATE TABLE user"), 0)

    def test_profile_keys_are_validated(self):
        for extra in ('env="staging"', 'env="test"\nconfirm="no"', 'confirm=false'):
            with self.subTest(extra=extra):
                add_profiles(self.h, profile("bad", extra))
                with self.assertRaises(tool.Fail):
                    tool.load_profiles()
                self.h.close()
                self.h = Home()

    def test_profiles_lists_the_test_ones(self):
        add_profiles(self.h, profile("loc", 'env="test"\nconfirm=false'))
        self.assertEqual({n for n, p in tool.load_profiles().items() if p.get("env") == "test"}, {"dev", "loc"})


class ExecTestGuard(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        with open(os.path.join(self.dir.name, "profiles.toml"), "w") as fh:
            fh.write('[profiles.prod]\nhost="db1.example.com"\nuser="u"\n'
                     '[profiles.dev]\nhost="127.0.0.1"\nuser="u"\nenv="test"\n'
                     '[profiles.remote_qa]\nhost="qa.example.com"\nuser="u"\nenv="test"\nconfirm=false\n'
                     '[profiles.local_free]\nhost="localhost"\nuser="u"\nenv="test"\nconfirm=false\n')

    def tearDown(self):
        self.dir.cleanup()

    def run_guard(self, cmd, home=None):
        env = {**os.environ, "DYNAMIA_MYSQL_HOME": home or self.dir.name}
        p = subprocess.run([sys.executable, GUARD], input=json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}}),
                           capture_output=True, text=True, env=env)
        if p.returncode == 2:
            return "deny", p.stderr
        return (json.loads(p.stdout)["hookSpecificOutput"]["permissionDecision"] if p.stdout.strip() else "allow"), p.stdout

    def test_a_test_profile_asks_every_time_by_default(self):
        for sql in ("DROP DATABASE shop_test", "TRUNCATE TABLE t", "DELETE FROM t", "UPDATE t SET a=1", "DELETE FROM t WHERE a > 3 AND b < 5"):
            with self.subTest(sql=sql):
                self.assertEqual(self.run_guard('mysql-tool exec-test dev "%s"' % sql)[0], "ask")
        self.assertEqual(self.run_guard("python3 /x/bin/mysql-tool exec-test dev 'DROP TABLE t'")[0], "ask")

    def test_confirm_false_is_silent_only_on_a_local_test_profile(self):
        self.assertEqual(self.run_guard('mysql-tool exec-test local_free "DROP TABLE t"')[0], "allow")
        self.assertEqual(self.run_guard('mysql-tool exec-test remote_qa "DROP TABLE t"')[0], "ask", "a remote host always asks")

    def test_a_profile_that_is_not_test_or_does_not_exist_is_denied(self):
        for name in ("prod", "nope"):
            kind, _ = self.run_guard('mysql-tool exec-test %s "DROP TABLE t"' % name)
            self.assertEqual(kind, "deny", name)

    def test_nothing_else_rides_along(self):
        for cmd in ('mysql-tool exec-test local_free "DROP TABLE t" && rm -rf x', 'mysql-tool exec-test local_free "DROP TABLE t" | tee o',
                    'mysql-tool exec-test local_free "DROP TABLE t" > out', 'mysql-tool exec-test local_free $(echo "DROP TABLE t")',
                    'mysql -h 127.0.0.1 -e "DROP TABLE t"', 'mysql-tool exec dev "DROP TABLE t"'):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.run_guard(cmd)[0], "deny")

    def test_passwords_stay_denied_on_a_test_profile(self):
        self.assertEqual(self.run_guard('mysql-tool exec-test local_free "UPDATE u SET a=1" -pSecret')[0], "deny")
        self.assertEqual(self.run_guard("mysql-tool exec-test local_free \"CREATE USER 'a'@'h' IDENTIFIED BY 'plain'\"")[0], "deny")

    def test_an_unreadable_profiles_file_asks_and_the_tool_decides(self):
        with tempfile.TemporaryDirectory() as empty:
            self.assertEqual(self.run_guard('mysql-tool exec-test dev "DROP TABLE t"', home=empty)[0], "ask")

    def test_the_denial_of_a_raw_destructive_statement_points_to_exec_test(self):
        kind, msg = self.run_guard("mysql -e 'DROP DATABASE shop'")
        self.assertEqual(kind, "deny")
        self.assertIn("exec-test PROFILE", msg)
        kind, msg = self.run_guard("mysql -u root -pSecret -e 'select 1'")
        self.assertEqual(kind, "deny")
        self.assertNotIn("exec-test", msg, "a password denial gets no hint")


if __name__ == "__main__":
    unittest.main()
