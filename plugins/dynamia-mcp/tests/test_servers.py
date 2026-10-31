import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
BIN = HERE.parent / "bin"
sys.path.insert(0, str(BIN))

import test_runner  # noqa: E402


class Server:
    """Talks to one server script over stdio, the way mcp-tool-chain does."""

    def __init__(self, script: str, **env: str):
        self.p = subprocess.Popen(
            [sys.executable, str(BIN / script)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
            env={**os.environ, **env},
        )
        self.n = 0
        self.rpc("initialize", {"protocolVersion": "2025-06-18"})

    def rpc(self, method: str, params: dict | None = None):
        self.n += 1
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params or {}}) + "\n")
        self.p.stdin.flush()
        return json.loads(self.p.stdout.readline())["result"]

    def tools(self) -> dict:
        return {t["name"]: t for t in self.rpc("tools/list")["tools"]}

    def call(self, _tool: str, **args):
        return self.rpc("tools/call", {"name": _tool, "arguments": args})

    def close(self):
        self.p.stdin.close()
        self.p.wait(timeout=5)
        self.p.stdout.close()


def value(r: dict):
    return r["structuredContent"] if "structuredContent" in r else json.loads(r["content"][0]["text"])


def git(repo: str, *argv: str):
    subprocess.run(["git", *argv], cwd=repo, check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


class Base(unittest.TestCase):
    def make_repo(self) -> str:
        d = tempfile.mkdtemp()
        self.addCleanup(subprocess.run, ["rm", "-rf", d])
        git(d, "init", "-q", "-b", "main")
        return d

    def serve(self, script: str, **env: str) -> Server:
        s = Server(script, **env)
        self.addCleanup(s.close)
        return s


class GhLite(Base):
    def setUp(self):
        self.s = self.serve("gh_lite.py", DYNAMIA_GH=str(HERE / "fake_gh"))

    def test_all_tools_are_read_only(self):
        self.assertTrue(all(t["annotations"]["readOnlyHint"] for t in self.s.tools().values()))

    def test_issue_state_reports_each_issue_and_keeps_going_after_an_error(self):
        rows = value(self.s.call("issue_state", numbers=[7, 9]))
        self.assertEqual(rows[0]["state"], "CLOSED")
        self.assertEqual(rows[0]["labels"], ["bug"])
        self.assertIn("no such issue", rows[1]["error"])

    def test_issue_state_refuses_bad_input(self):
        self.assertTrue(self.s.call("issue_state", numbers=["7"])["isError"])

    def test_pr_status_summarizes_checks(self):
        pr = value(self.s.call("pr_status", number=3))
        self.assertEqual(pr["checks"], {"total": 3, "failing": ["lint"], "pending": ["e2e"], "ok": False})
        self.assertEqual(pr["closes"], [7])
        self.assertEqual(pr["review"], "NONE")

    def test_checks_lists_only_the_bad_ones_and_reads_both_entry_kinds(self):
        c = value(self.s.call("checks", number=3))
        self.assertEqual(c["rows"], [{"name": "lint", "state": "FAILURE"}])
        self.assertEqual(c["total"], 2)

    def test_issues_closed_by(self):
        self.assertEqual(value(self.s.call("issues_closed_by", number=3)), {"state": "MERGED", "closes": [7]})


class RepoMap(Base):
    def setUp(self):
        self.repo = self.make_repo()
        Path(self.repo, "Foo.java").write_text("public class Foo {\n  public int total(int a) {\n    if (a > 0) { return a; }\n    return 0;\n  }\n}\n")
        Path(self.repo, "FooTest.java").write_text("class FooTest { void totalWorks() {} }\n")
        Path(self.repo, "mod.py").write_text("class A:\n    def run(self):\n        pass\n\nasync def go():\n    pass\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "init")
        self.s = self.serve("repo_map.py", DYNAMIA_ROOT=self.repo)

    def test_symbols_java_skips_control_flow(self):
        names = [(r["kind"], r["name"]) for r in value(self.s.call("symbols", file="Foo.java"))]
        self.assertEqual(names, [("class", "Foo"), ("method", "total")])

    def test_symbols_python(self):
        self.assertEqual([r["name"] for r in value(self.s.call("symbols", file="mod.py"))], ["A", "run", "go"])

    def test_symbols_refuses_paths_outside_the_project(self):
        self.assertTrue(self.s.call("symbols", file="../../etc/passwd")["isError"])

    def test_callers_finds_whole_words(self):
        hits = value(self.s.call("callers", name="total"))
        self.assertEqual(hits["total"], 1)
        self.assertEqual(hits["hits"][0]["file"], "Foo.java")

    def test_callers_refuses_a_non_identifier(self):
        self.assertTrue(self.s.call("callers", name="-e x")["isError"])

    def test_changed_since_lists_edits_and_untracked(self):
        Path(self.repo, "Foo.java").write_text("public class Foo {}\n")
        Path(self.repo, "new.txt").write_text("x")
        rows = {r["file"]: r["status"] for r in value(self.s.call("changed_since"))}
        self.assertEqual(rows, {"Foo.java": "M", "new.txt": "?"})

    def test_changed_since_refuses_an_option_as_ref(self):
        self.assertTrue(self.s.call("changed_since", ref="--output=x")["isError"])

    def test_tests_for(self):
        self.assertEqual(value(self.s.call("tests_for", file="src/Foo.java")), ["FooTest.java"])


class GitOverview(Base):
    def test_one_repo_and_a_folder_of_repos(self):
        repo = self.make_repo()
        Path(repo, "a").write_text("1")
        git(repo, "add", "."), git(repo, "commit", "-qm", "first")
        Path(repo, "b").write_text("2")
        row = value(self.serve("git_overview.py", DYNAMIA_ROOT=repo).call("repos"))[0]
        self.assertEqual((row["branch"], row["dirty"], row["ahead"], row["last"][8:]), ("main", 1, None, "first"))

        parent = tempfile.mkdtemp()
        self.addCleanup(subprocess.run, ["rm", "-rf", parent])
        for name in ("one", "two"):
            os.mkdir(f"{parent}/{name}")
            git(f"{parent}/{name}", "init", "-q")
        rows = value(self.serve("git_overview.py", DYNAMIA_ROOT=parent).call("repos"))
        self.assertEqual([r["repo"] for r in rows], ["one", "two"])

    def test_no_repo_is_an_error(self):
        d = tempfile.mkdtemp()
        self.addCleanup(subprocess.run, ["rm", "-rf", d])
        self.assertTrue(self.serve("git_overview.py", DYNAMIA_ROOT=d).call("repos")["isError"])


class TestRunner(Base):
    def test_parsers(self):
        sure = "[ERROR] Failures: \n[ERROR]   FooTest.bar:12 expected 1 but was 2\n[ERROR] Tests run: 5, Failures: 1, Errors: 0, Skipped: 0\n"
        r = test_runner.parse(sure, 1)
        self.assertEqual(r["failures"], [{"test": "FooTest.bar:12", "msg": "expected 1 but was 2"}])
        self.assertTrue(r["summary"].startswith("Tests run: 5"))

        unit = "FAIL: test_x (tests.T.test_x)\n\nRan 3 tests in 0.1s\n\nFAILED (failures=1)\n"
        self.assertEqual(test_runner.parse(unit, 1)["failures"][0]["test"], "test_x (tests.T.test_x)")

        bun = "(pass) a\n(fail) b [1.2ms]\n\n 1 pass\n 1 fail\n"
        self.assertEqual(test_runner.parse(bun, 1)["failures"][0]["test"], "b")

    def test_a_build_error_returns_problems_and_the_tail(self):
        r = test_runner.parse("[INFO] start\n[ERROR] COMPILATION ERROR :\n[ERROR] Foo.java:[3,1] cannot find symbol\n", 1)
        self.assertEqual(r["failures"], [])
        self.assertEqual(len(r["problems"]), 2)
        self.assertTrue(r["tail"])

    def test_a_pass_has_no_noise(self):
        self.assertEqual(test_runner.parse("Ran 2 tests in 0.0s\n\nOK\n", 0), {"exit": 0, "passed": True, "summary": "Ran 2 tests in 0.0s", "failures": []})

    def test_runs_a_command_and_reports_only_the_failure(self):
        repo = self.make_repo()
        Path(repo, "test_a.py").write_text("import unittest\nclass T(unittest.TestCase):\n    def test_x(self): self.assertEqual(1, 2)\n    def test_y(self): pass\n")
        s = self.serve("test_runner.py", DYNAMIA_ROOT=repo)
        self.assertFalse(s.tools()["run"]["annotations"]["readOnlyHint"])
        r = value(s.call("run", command="python3 -m unittest test_a"))
        self.assertFalse(r["passed"])
        self.assertEqual([f["test"] for f in r["failures"]], ["test_x (test_a.T.test_x)"])

    def test_refuses_commands_off_the_list_and_cwd_outside(self):
        s = self.serve("test_runner.py", DYNAMIA_ROOT=self.make_repo())
        self.assertTrue(s.call("run", command="rm -rf /")["isError"])
        self.assertTrue(s.call("run", command="pytest", cwd="..")["isError"])


class Board(Base):
    def setUp(self):
        self.repo = self.make_repo()
        git(self.repo, "remote", "add", "origin", "git@github.com:o/r.git")
        self.state = tempfile.mkdtemp()
        self.addCleanup(subprocess.run, ["rm", "-rf", self.state])
        self.env = {"DYNAMIA_ROOT": self.repo, "DYNAMIA_STATE": self.state}

    def test_set_list_and_drop_persist_between_servers(self):
        s = self.serve("board.py", **self.env)
        r = value(s.call("set", updates=[{"n": 1, "state": "work", "title": "One"}, {"n": 2, "state": "pr"}]))
        self.assertEqual(r["changed"], ["#1 work", "#2 pr"])
        value(s.call("set", updates=[{"n": 1, "state": "done"}, {"n": 2, "state": "drop"}]))

        again = self.serve("board.py", **self.env)
        rows = value(again.call("list"))
        self.assertEqual([(i["n"], i["state"], i["title"]) for i in rows], [(1, "done", "One")])
        self.assertEqual(value(again.call("list", state="work")), [])
        self.assertEqual(value(again.call("clear")), {"cleared": True})
        self.assertEqual(value(again.call("list")), [])

    def test_a_list_result_is_text_json_only_so_a_chain_gets_the_list_itself(self):
        s = self.serve("board.py", **self.env)
        r = s.call("list")
        self.assertNotIn("structuredContent", r)
        self.assertEqual(json.loads(r["content"][0]["text"]), [])
        self.assertIn("structuredContent", s.call("clear"))

    def test_bad_updates_and_a_missing_remote_are_errors(self):
        s = self.serve("board.py", **self.env)
        self.assertTrue(s.call("set", updates=[{"n": "1", "state": "work"}])["isError"])
        self.assertTrue(s.call("set", updates=[{"n": 1, "state": "nope"}])["isError"])
        self.assertTrue(s.call("set")["isError"])
        bare = self.serve("board.py", DYNAMIA_ROOT=self.make_repo(), DYNAMIA_STATE=self.state)
        self.assertTrue(bare.call("list")["isError"])


if __name__ == "__main__":
    unittest.main()
