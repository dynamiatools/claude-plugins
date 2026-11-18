import contextlib
import io
import os
import sys
import tempfile
import unittest

from _env import Home, load

tool = load("mysql-tool")
guard = load("mysql-guard")

PW = "s3cr3t-pw!"  # the PROD_PW secret of the throwaway Home


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = tool.main(list(argv))
        except tool.Fail as e:
            return 1, out.getvalue(), str(e)
    return rc or 0, out.getvalue(), err.getvalue()


class RunTest(unittest.TestCase):
    def setUp(self):
        self.h = Home()
        self.tmp = tempfile.TemporaryDirectory()
        self.out = os.path.join(self.tmp.name, "out.txt")

    def tearDown(self):
        self.tmp.cleanup()
        self.h.close()

    def child(self, code):
        return [sys.executable, "-c", code, self.out]

    def test_child_gets_the_filled_variables_and_the_exit_code(self):
        code = "import os,sys; open(sys.argv[1],'w').write('|'.join([os.environ['U'], os.environ['URL'], os.environ['PW']])); sys.exit(3)"
        rc, out, err = run("run", "src", "--env", "U={user}", "--env", "URL=jdbc:mysql://{host}:{port}/x", "--env", "PW={password}", "--", *self.child(code))
        self.assertEqual(rc, 3)
        with open(self.out) as fh:
            self.assertEqual(fh.read(), "dba|jdbc:mysql://10.0.0.1:3306/x|" + PW)

    def test_the_password_never_reaches_the_output(self):
        code = "import os; print('pw=' + os.environ['PW'])"
        rc, out, err = run("run", "src", "--env", "PW={password}", "--", sys.executable, "-c", code)
        self.assertEqual(rc, 0)
        self.assertIn("pw=***", out)
        self.assertNotIn(PW, out + err)

    def test_refuses_unknown_field_missing_db_and_no_env(self):
        base = ["run", "src", "--"]
        self.assertIn("unknown field", run("run", "src", "--env", "A={passwd}", "--", "true")[2])
        self.assertIn("does not have", run("run", "src", "--env", "A={db}", "--", "true")[2])  # the profile has no db
        self.assertIn("at least one --env", run(*base, "true")[2])
        self.assertIn("nothing to run", run("run", "src", "--env", "A={user}")[2])

    def test_missing_secret_is_reported_without_a_value(self):
        with open(os.path.join(self.h.dir.name, "secrets.env"), "w") as fh:
            fh.write("")
        os.chmod(os.path.join(self.h.dir.name, "secrets.env"), 0o600)
        rc, out, err = run("run", "src", "--env", "A={password}", "--", "true")
        self.assertEqual(rc, 2)
        self.assertIn("PROD_PW is not set", err)

    def test_guard_asks_before_running_a_command_with_the_password(self):
        cmd = "python3 bin/mysql-tool run dynamiaerp --env DB_PASSWORD={password} -- ./mvnw spring-boot:run"
        self.assertEqual(guard.check("Bash", {"command": cmd})[0], "ask")


if __name__ == "__main__":
    unittest.main()
