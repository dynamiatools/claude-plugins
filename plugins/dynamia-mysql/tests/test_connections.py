import contextlib
import io
import json
import os
import stat
import tempfile
import unittest

from _env import Home, load

tool = load("mysql-tool")


def rj(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def rtext(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def wj(path, data):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = tool.main(list(argv))
        except tool.Fail as e:
            return 1, out.getvalue(), str(e)
    return rc or 0, out.getvalue(), err.getvalue()


class ConnectionsTest(unittest.TestCase):
    def setUp(self):
        self.h = Home({"select": "id\n1\n2\n"})
        self.ws = tempfile.TemporaryDirectory()
        os.makedirs(os.path.join(self.ws.name, ".dynamia"))
        self.sub = os.path.join(self.ws.name, "repo", "src")
        os.makedirs(self.sub)
        self.cwd = os.getcwd()
        os.chdir(self.sub)
        self.ws_file = os.path.join(os.path.realpath(self.ws.name), ".dynamia", "mysql", "connections.json")
        self.user_file = os.path.join(self.h.dir.name, "connections.json")

    def tearDown(self):
        os.chdir(self.cwd)
        self.ws.cleanup()
        self.h.close()

    def add(self, *extra, name="shop"):
        fake = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fake_client.py")
        return run("conn-add", name, "--host", "db.example.com", "--user", "ro", "--secret", "PROD_PW", "--client", fake, *extra)

    def test_auto_scope_is_the_workspace_found_by_walking_up(self):
        rc, out, _ = self.add("--db", "shop")
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.exists(self.ws_file))
        self.assertFalse(os.path.exists(self.user_file))
        data = rj(self.ws_file)
        self.assertEqual(data["connections"]["shop"], {"host": "db.example.com", "user": "ro", "secret": "PROD_PW", "client": data["connections"]["shop"]["client"], "db": "shop"})
        self.assertNotIn("s3cr3t-pw!", rtext(self.ws_file))
        self.assertEqual(tool.get_profile("shop")["host"], "db.example.com")  # added here, so already trusted

    def test_user_scope_file_is_private_and_works_without_a_workspace(self):
        os.chdir(self.cwd if not os.path.isdir(os.path.join(self.cwd, ".dynamia")) else tempfile.gettempdir())
        rc, _, _ = self.add("--scope", "user")
        self.assertEqual(rc, 0)
        self.assertEqual(stat.S_IMODE(os.stat(self.user_file).st_mode), 0o600)
        self.assertIn("shop", tool.load_profiles())

    def test_workspace_scope_without_a_workspace_is_an_error(self):
        os.chdir(tempfile.gettempdir())
        if tool.workspace_dir():
            self.skipTest("the temp dir sits inside a .dynamia workspace")
        rc, _, err = self.add("--scope", "workspace")
        self.assertEqual(rc, 2)
        self.assertIn(".dynamia", err)

    def test_passwords_env_and_unknown_keys_are_refused(self):
        for bad in ({"user": "u", "host": "h", "password": "x"}, {"user": "u", "host": "h", "env": "test"},
                    {"user": "u", "host": "h", "confirm": False}, {"user": "u", "host": "h", "pwd": "x"},
                    {"user": "u", "host": "h", "extra": 1}, {"user": "u", "host": "h; x"}, {"host": "h"}, {"user": "u"}):
            with self.assertRaises(tool.Fail, msg=bad):
                tool.check_connection("c", bad)
        with self.assertRaises(tool.Fail):
            tool.check_connection("bad name", {"user": "u", "host": "h"})

    def test_hand_edited_file_with_a_password_is_refused_when_read(self):
        os.makedirs(os.path.dirname(self.ws_file))
        wj(self.ws_file, {"connections": {"x": {"host": "h", "user": "u", "password": "p"}}})
        with self.assertRaises(tool.Fail):
            tool.load_profiles()

    def test_a_workspace_connection_from_someone_else_needs_trust(self):
        os.makedirs(os.path.dirname(self.ws_file))
        wj(self.ws_file, {"connections": {"evil": {"host": "attacker.example", "user": "u", "secret": "PROD_PW"}}})
        self.assertNotIn("evil", tool.load_profiles())
        with self.assertRaises(tool.Fail) as cm:
            tool.get_profile("evil")
        self.assertIn("conn-trust evil", str(cm.exception))
        self.assertIn("NOT TRUSTED", run("conn-list")[1])
        self.assertEqual(self.h.calls(), [])  # nothing was sent anywhere
        self.assertEqual(run("conn-trust", "evil")[0], 0)
        self.assertEqual(tool.get_profile("evil")["host"], "attacker.example")

    def test_changing_the_host_of_a_trusted_connection_revokes_trust(self):
        self.add()
        data = rj(self.ws_file)
        data["connections"]["shop"]["host"] = "other.example.com"
        wj(self.ws_file, data)
        with self.assertRaises(tool.Fail):
            tool.get_profile("shop")
        data["connections"]["shop"]["db"] = "x"  # a description or db change alone does not matter
        data["connections"]["shop"]["host"] = "db.example.com"
        wj(self.ws_file, data)
        self.assertEqual(tool.get_profile("shop")["db"], "x")

    def test_precedence_profiles_then_workspace_then_user(self):
        run("conn-add", "src", "--host", "ws.example.com", "--user", "u")  # same name as a profiles.toml entry
        self.assertEqual(tool.get_profile("src")["host"], "10.0.0.1")
        run("conn-add", "dup", "--host", "user.example.com", "--user", "u", "--scope", "user")
        run("conn-add", "dup", "--host", "ws.example.com", "--user", "u", "--scope", "workspace")
        self.assertEqual(tool.get_profile("dup")["host"], "ws.example.com")

    def test_duplicate_needs_force_and_remove_needs_a_scope_when_ambiguous(self):
        self.assertEqual(self.add()[0], 0)
        self.assertEqual(self.add()[0], 2)
        self.assertEqual(self.add("--force")[0], 0)
        run("conn-add", "shop", "--host", "u.example.com", "--user", "u", "--scope", "user")
        self.assertEqual(run("conn-remove", "shop")[0], 2)
        self.assertEqual(run("conn-remove", "shop", "--scope", "workspace")[0], 0)
        self.assertEqual(tool.get_profile("shop")["host"], "u.example.com")
        self.assertEqual(run("conn-remove", "nope")[0], 2)

    def test_query_uses_the_connection_db_and_the_secret_stays_out_of_argv(self):
        self.add("--db", "shop")
        rc, out, _ = run("query", "shop", "SELECT id FROM orders")
        self.assertEqual(rc, 0)
        call = self.h.calls()[0]
        self.assertIn("--database=shop", call["args"])
        self.assertNotIn("s3cr3t-pw!", " ".join(call["args"]))
        run("query", "shop", "SELECT id FROM orders", "--db", "other")
        self.assertIn("--database=other", self.h.calls()[1]["args"])

    def test_a_connection_can_never_run_destructive_test_statements(self):
        self.add()
        rc, _, err = run("exec-test", "shop", "TRUNCATE TABLE t")
        self.assertEqual(rc, 2)
        self.assertEqual(self.h.calls(), [])

    def test_list_shows_names_not_values(self):
        self.add("--db", "shop")
        rc, out, _ = run("conn-list")
        self.assertIn("shop\tworkspace\tro@db.example.com:3306\tdb=shop\tsecret=PROD_PW", out)
        self.assertIn("src\tprofiles.toml", out)
        self.assertNotIn("s3cr3t-pw!", out)

    def test_add_warns_when_the_secret_is_not_set(self):
        rc, out, _ = run("conn-add", "x", "--host", "h", "--user", "u", "--secret", "MISSING_PW")
        self.assertIn("secret-set MISSING_PW", out)


if __name__ == "__main__":
    unittest.main()
