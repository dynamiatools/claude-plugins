import contextlib
import io
import os
import unittest

from _env import Home, load

tool = load("mysql-tool")


class QueryTest(unittest.TestCase):
    def setUp(self):
        self.h = Home({"select": "id\n" + "".join("%d\n" % i for i in range(1, 6))})
        self.prof = tool.get_profile("src")

    def tearDown(self):
        self.h.close()

    def test_rows_over_the_limit_are_cut_and_flagged(self):
        rs, cut = tool.run_query(self.prof, "SELECT id FROM t", limit=3)
        self.assertEqual([r["id"] for r in rs], ["1", "2", "3"])
        self.assertTrue(cut)

    def test_under_the_limit_is_not_flagged_and_zero_means_no_cap(self):
        rs, cut = tool.run_query(self.prof, "SELECT id FROM t", limit=10)
        self.assertEqual((len(rs), cut), (5, False))
        rs, cut = tool.run_query(self.prof, "SELECT id FROM t", limit=0)
        self.assertEqual((len(rs), cut), (5, False))
        self.assertNotIn("sql_select_limit", self.h.calls()[-1]["sql"])

    def test_session_limits_are_sent_before_the_statement(self):
        tool.run_query(self.prof, "SELECT id FROM t", limit=3, timeout=7)
        call = self.h.calls()[0]
        self.assertIn("MAX_EXECUTION_TIME=7000", call["sql"])
        self.assertIn("sql_select_limit=4", call["sql"])
        self.assertLess(call["sql"].index("MAX_EXECUTION_TIME"), call["sql"].index("SELECT id"))
        self.assertIn("--init-command=SET SESSION TRANSACTION READ ONLY", call["args"])

    def test_mariadb_uses_max_statement_time(self):
        os.environ["FAKE_VERSION"] = "mariadb  Ver 15.1 Distrib 11.4.2-MariaDB"
        try:
            tool._MARIADB_CLIENT.clear()
            tool.run_query(self.prof, "SELECT id FROM t", timeout=7)
            self.assertIn("max_statement_time=7", self.h.calls()[0]["sql"])
        finally:
            os.environ.pop("FAKE_VERSION")
            tool._MARIADB_CLIENT.clear()

    def test_db_is_passed_to_the_client_and_validated(self):
        tool.run_query(self.prof, "SELECT id FROM t", database="shop")
        self.assertIn("--database=shop", self.h.calls()[0]["args"])
        for bad in ("shop; x", "a b", "`x`", ""):
            with self.assertRaises(tool.Fail):
                tool.run_query(self.prof, "SELECT 1", database=bad)

    def test_statements_that_are_not_plain_reads_never_reach_the_client(self):
        for sql in ("DELETE FROM t WHERE id = 1", "SELECT 1; SELECT 2", "SELECT * FROM t INTO OUTFILE '/tmp/x'",
                    "SELECT SLEEP(5)", "UPDATE t SET a = 1 WHERE id = 1"):
            with self.assertRaises(tool.Fail):
                tool.run_query(self.prof, sql)
        self.assertEqual(self.h.calls(), [])

    def test_bad_numbers_are_refused(self):
        with self.assertRaises(tool.Fail):
            tool.run_query(self.prof, "SELECT 1", limit=-1)
        with self.assertRaises(tool.Fail):
            tool.run_query(self.prof, "SELECT 1", timeout=0)

    def test_cli_prints_truncation_note_on_stderr(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = tool.main(["query", "src", "SELECT id FROM t", "--limit", "2"])
        self.assertEqual(rc or 0, 0)
        self.assertEqual(out.getvalue().split("\n")[:3], ["id", "1", "2"])
        self.assertIn("truncated at 2 rows", err.getvalue())


if __name__ == "__main__":
    unittest.main()
