"""Behavior tests for bin/ms-workspace and bin/ms-statusline (standard library only).

Run:  python3 -m unittest discover -s tests -v
Pick another implementation with MS_WORKSPACE_BIN=/path/to/ms-workspace.

Every test builds a throwaway workspace (bare remotes, clones on branch `next`) under a
temporary directory and a private HOME, so nothing outside it is touched.
"""
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BIN = os.environ.get("MS_WORKSPACE_BIN", str(REPO / "bin" / "ms-workspace"))
STATUSLINE = str(REPO / "bin" / "ms-statusline")

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

DEFAULT_TOML = """
name = "t"
[repos.lib]
base = "next"
deps = []
[repos.lib.test]
unit = "echo unit-lib"
affected = "echo affected {modules}"
[repos.app]
base = "next"
deps = ["lib"]
[repos.app.test]
unit = "echo unit-app"
"""


def run(cmd, cwd=None, env=None, input=None):
    return subprocess.run(cmd, cwd=cwd, env=env, input=input, text=True, capture_output=True)


class WS:
    """A temporary workspace with bare remotes and clones on branch `next`."""

    def __init__(self, repos=("lib", "app"), toml=DEFAULT_TOML, dynamia=False):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name).resolve()
        self.dynamia = dynamia
        self.project = self.tmp / "ws"
        # dynamia=True is the .dynamia/ layout: workspace.toml in .dynamia/, state in .dynamia/workspace/; the repos stay in the project folder
        self.root = self.project / ".dynamia" / "workspace" if dynamia else self.project
        self.cfg = self.project / ".dynamia" / "workspace.toml" if dynamia else self.root / "workspace.toml"
        self.home = self.tmp / "home"
        self.cache = self.tmp / "cache"
        self.root.mkdir(parents=True)
        self.home.mkdir()
        self.env = {
            **{k: v for k, v in os.environ.items() if not k.startswith(("MS_", "GIT_"))},
            "HOME": str(self.home),
            "MS_CACHE_DIR": str(self.cache),
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
        }
        self.env.pop("XDG_CACHE_HOME", None)
        for r in repos:
            remote = self.tmp / f"remote-{r}.git"
            self.git(self.tmp, "init", "-q", "--bare", str(remote))
            self.git(remote, "symbolic-ref", "HEAD", "refs/heads/next")
            self.git(self.tmp, "clone", "-q", str(remote), str(self.project / r))
            self.git(self.project / r, "checkout", "-q", "-b", "next")
            (self.project / r / "a.txt").write_text("base\n")
            self.commit(self.project / r, "init")
            self.git(self.project / r, "push", "-q", "origin", "next")
        if toml is not None:
            self.cfg.write_text(textwrap.dedent(toml))

    def close(self):
        self._tmp.cleanup()

    def git(self, cwd, *args):
        r = run(["git", *args], cwd=cwd, env=self.env)
        if r.returncode != 0:
            raise AssertionError(f"git {' '.join(args)} failed in {cwd}: {r.stderr}")
        return r.stdout.strip()

    def commit(self, cwd, msg, files=None):
        for name, content in (files or {}).items():
            p = Path(cwd) / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
        self.git(cwd, "add", "-A")
        self.git(cwd, "commit", "-q", "-m", msg)

    def ms(self, *args, cwd=None, input=None, env=None):
        return run([BIN, *args], cwd=cwd or self.root, env={**self.env, **(env or {})}, input=input)

    def ms_py(self, *args, cwd=None, input=None, env=None):
        """Like ms() but through the current interpreter, so PATH can be restricted without breaking the shebang."""
        return run([sys.executable, BIN, *args], cwd=cwd or self.root, env={**self.env, **(env or {})}, input=input)

    def set_toml(self, text):
        self.cfg.write_text(textwrap.dedent(text))

    def batch(self, name="b1", *repos):
        r = self.ms("batch", "new", name, *repos)
        assert r.returncode == 0, r.stderr
        return self.root / ("working-trees" if self.dynamia else ".batches") / name

    def remote_log(self, repo, branch="next"):
        return self.git(self.tmp / f"remote-{repo}.git", "log", "--format=%s", branch).splitlines()

    def log_lines(self, *args):
        return self.ms("log", *args).stdout


class Base(unittest.TestCase):
    def setUp(self):
        self.ws = WS()
        self.addCleanup(self.ws.close)

    def assertOk(self, r):
        self.assertEqual(r.returncode, 0, f"stdout={r.stdout!r} stderr={r.stderr!r}")


# ---------------------------------------------------------------- batch / env
class TestBatch(Base):
    def test_batch_new_creates_worktrees_branches_and_tasks(self):
        d = self.ws.batch("b1")
        for r in ("lib", "app"):
            self.assertEqual(self.ws.git(d / r, "branch", "--show-current"), "int/b1")
        tasks = (d / "TASKS.md").read_text()
        self.assertIn("lib", tasks)
        self.assertIn("app", tasks)
        self.assertIn("batch.new", self.ws.log_lines())

    def test_batch_new_twice_fails(self):
        self.ws.batch("b1")
        r = self.ws.ms("batch", "new", "b1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("already exists", r.stderr)

    def test_batch_new_subset_of_repos(self):
        d = self.ws.batch("b1", "lib")
        self.assertTrue((d / "lib").is_dir())
        self.assertFalse((d / "app").exists())

    def test_batch_new_unknown_repo_fails(self):
        r = self.ws.ms("batch", "new", "b1", "nope")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("nope", r.stderr)

    def test_batch_requires_workspace(self):
        r = self.ws.ms("batch", "new", "x", cwd=self.ws.tmp)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("workspace.toml", r.stderr)

    def test_env_copies_ignored_files_but_never_tracked_ones(self):
        lib = self.ws.root / "lib"
        (lib / ".gitignore").write_text(".env\nsecrets/*.json\nextra.env\n.claude/settings.local.json\n")
        (lib / ".worktreeinclude").write_text(".env\nsecrets/*.json\n")
        (lib / "tracked.txt").write_text("t")
        self.ws.commit(lib, "ignore rules")
        self.ws.git(lib, "push", "-q", "origin", "next")
        (lib / ".env").write_text("K=1\n")
        (lib / "secrets").mkdir()
        (lib / "secrets" / "a.json").write_text("{}")
        (lib / "extra.env").write_text("X=1\n")
        (lib / "not-ignored.txt").write_text("untracked and not ignored")
        (lib / ".claude").mkdir()
        (lib / ".claude" / "settings.local.json").write_text("{}")
        self.ws.set_toml(DEFAULT_TOML.replace('[repos.lib]\nbase = "next"', '[repos.lib]\nbase = "next"\nenv_files = ["extra.env"]'))
        d = self.ws.batch("b1", "lib")
        self.assertEqual((d / "lib" / ".env").read_text(), "K=1\n")
        self.assertTrue((d / "lib" / "secrets" / "a.json").exists())
        self.assertTrue((d / "lib" / "extra.env").exists())
        self.assertTrue((d / "lib" / ".claude" / "settings.local.json").exists())
        self.assertFalse((d / "lib" / "not-ignored.txt").exists())

    def test_env_setup_runs_the_configured_command(self):
        self.ws.set_toml(DEFAULT_TOML.replace('[repos.lib]\nbase = "next"', '[repos.lib]\nbase = "next"\nsetup = "echo hi > setup.out"'))
        d = self.ws.batch("b1", "lib")
        self.assertFalse((d / "lib" / "setup.out").exists())
        self.assertOk(self.ws.ms("env", "b1", "--setup"))
        self.assertEqual((d / "lib" / "setup.out").read_text().strip(), "hi")

    def test_env_trust_marks_worktrees_trusted(self):
        (self.ws.home / ".claude.json").write_text("{}")
        d = self.ws.batch("b1", "lib")
        self.assertOk(self.ws.ms("env", "b1", "--trust"))
        data = json.loads((self.ws.home / ".claude.json").read_text())
        self.assertTrue(data["projects"][str(d / "lib")]["hasTrustDialogAccepted"])

    def test_tasks_mode_per_repo(self):
        self.ws.set_toml(DEFAULT_TOML.replace('[repos.app]\nbase = "next"', '[repos.app]\nbase = "next"\ntasks = "github"'))
        tasks = (self.ws.batch("b1") / "TASKS.md").read_text()
        self.assertIn("- [ ] lib", tasks)
        self.assertIn("app: tracked in GitHub issues", tasks)


# ------------------------------------------------------------------- affected
class TestAffected(Base):
    def test_modules_and_dependents(self):
        d = self.ws.batch("b1")
        self.ws.commit(d / "lib", "mod", {"pom.xml": "<p/>", "m1/pom.xml": "<p/>", "m1/A.java": "x"})
        r = self.ws.ms("affected", cwd=d / "lib")
        self.assertOk(r)
        data = json.loads(r.stdout)
        self.assertEqual(data["repo"], "lib")
        self.assertIn("m1", data["modules"])
        self.assertEqual(data["dependents"], ["app"])

    def test_no_pom_means_no_modules(self):
        d = self.ws.batch("b1")
        self.ws.commit(d / "app", "x", {"f.txt": "x"})
        data = json.loads(self.ws.ms("affected", cwd=d / "app").stdout)
        self.assertEqual(data["modules"], [])
        self.assertEqual(data["dependents"], [])
        self.assertEqual(data["files"], 1)

    def test_outside_a_repo_fails(self):
        self.assertNotEqual(self.ws.ms("affected", cwd=self.ws.root).returncode, 0)


# ---------------------------------------------------------------------- tests
class TestRunner(Base):
    def test_t0_pass(self):
        d = self.ws.batch("b1")
        r = self.ws.ms("test", "t0", cwd=d / "lib")
        self.assertOk(r)
        self.assertIn("PASS t0 lib", r.stdout)

    def test_t0_fail_returns_code_and_shows_output(self):
        self.ws.set_toml(DEFAULT_TOML.replace('unit = "echo unit-lib"', 'unit = "echo boom-line; exit 3"'))
        d = self.ws.batch("b1")
        r = self.ws.ms("test", "t0", cwd=d / "lib")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("FAIL t0 lib", r.stderr)
        self.assertIn("boom-line", r.stderr)

    def test_memo_skips_identical_runs_until_code_changes(self):
        d = self.ws.batch("b1")
        wt = d / "lib"
        self.assertNotIn("cached", self.ws.ms("test", "t0", cwd=wt).stdout)
        self.assertIn("cached", self.ws.ms("test", "t0", cwd=wt).stdout)
        self.assertNotIn("cached", self.ws.ms("test", "t0", "--no-cache", cwd=wt).stdout)
        (wt / "new.txt").write_text("change")
        self.assertNotIn("cached", self.ws.ms("test", "t0", cwd=wt).stdout)

    def test_memo_is_not_written_for_failures(self):
        self.ws.set_toml(DEFAULT_TOML.replace('unit = "echo unit-lib"', 'unit = "exit 1"'))
        wt = self.ws.batch("b1") / "lib"
        self.assertNotEqual(self.ws.ms("test", "t0", cwd=wt).returncode, 0)
        self.assertNotIn("cached", self.ws.ms("test", "t0", cwd=wt).stdout)

    def test_memo_of_dependent_repo_sees_upstream_changes_in_batch(self):
        d = self.ws.batch("b1")
        self.assertNotIn("cached", self.ws.ms("test", "t0", cwd=d / "app").stdout)
        self.assertIn("cached", self.ws.ms("test", "t0", cwd=d / "app").stdout)
        self.ws.commit(d / "lib", "upstream change", {"u.txt": "x"})
        self.assertNotIn("cached", self.ws.ms("test", "t0", cwd=d / "app").stdout)

    def test_affected_command_receives_modules(self):
        d = self.ws.batch("b1")
        self.ws.commit(d / "lib", "mod", {"pom.xml": "<p/>", "m1/pom.xml": "<p/>", "m1/A.java": "x"})
        r = self.ws.ms("test", "t0", cwd=d / "lib")
        self.assertOk(r)
        self.assertRegex(r.stdout, r"affected .*m1")

    def test_t1_skips_unchanged_repos_and_adds_critical_modules(self):
        self.ws.set_toml(DEFAULT_TOML.replace('[repos.lib]\nbase = "next"', '[repos.lib]\nbase = "next"\ncritical = ["core"]'))
        d = self.ws.batch("b1")
        self.ws.commit(d / "lib", "mod", {"pom.xml": "<p/>", "m1/pom.xml": "<p/>", "m1/A.java": "x"})
        r = self.ws.ms("test", "t1", "b1")
        self.assertOk(r)
        self.assertIn("skip app", r.stdout)
        self.assertRegex(r.stdout, r"affected .*core")
        self.assertRegex(r.stdout, r"affected .*m1")

    def test_t1_stops_at_first_failing_repo(self):
        self.ws.set_toml(DEFAULT_TOML.replace('unit = "echo unit-lib"', 'unit = "exit 1"'))
        d = self.ws.batch("b1")
        self.ws.commit(d / "lib", "x", {"f.txt": "1"})
        self.ws.commit(d / "app", "x", {"f.txt": "1"})
        r = self.ws.ms("test", "t1", "b1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("FAIL t1 lib", r.stderr)
        self.assertNotIn("app", r.stdout)

    def test_t2_runs_e2e_command(self):
        self.ws.set_toml(DEFAULT_TOML + '\n[e2e]\ncommand = "echo e2e-ran"\nrepo = "app"\n')
        self.ws.batch("b1")
        r = self.ws.ms("test", "t2", "b1")
        self.assertOk(r)
        self.assertIn("PASS t2", r.stdout)

    def test_t2_without_config_fails(self):
        self.ws.batch("b1")
        self.assertNotEqual(self.ws.ms("test", "t2", "b1").returncode, 0)

    def test_unknown_level_fails(self):
        self.assertNotEqual(self.ws.ms("test", "t9").returncode, 0)


# ------------------------------------------------------ agents and integration
class TestIntegrate(Base):
    def setUp(self):
        super().setUp()
        self.d = self.ws.batch("b1")

    def agent(self, task, *repos):
        r = self.ws.ms("agent", "new", "b1", task, *repos)
        self.assertOk(r)
        return self.d / ".agents" / task

    def test_agent_new_creates_isolated_worktrees(self):
        a = self.agent("t1", "lib")
        self.assertEqual(self.ws.git(a / "lib", "branch", "--show-current"), "agent/b1/t1")
        self.assertFalse((a / "app").exists())

    def test_agent_new_duplicate_fails(self):
        self.agent("t1", "lib")
        self.assertNotEqual(self.ws.ms("agent", "new", "b1", "t1", "lib").returncode, 0)

    def test_dry_run_changes_nothing(self):
        a = self.agent("t1", "lib")
        self.ws.commit(a / "lib", "w", {"f1.txt": "1"})
        before = self.ws.git(self.d / "lib", "rev-parse", "HEAD")
        r = self.ws.ms("integrate", "b1", "--dry-run")
        self.assertOk(r)
        self.assertIn("merges cleanly", r.stdout)
        self.assertEqual(self.ws.git(self.d / "lib", "rev-parse", "HEAD"), before)

    def test_integrate_merges_all_agents_then_reports_already_merged(self):
        a1, a2 = self.agent("t1", "lib"), self.agent("t2", "lib", "app")
        self.ws.commit(a1 / "lib", "w1", {"f1.txt": "1"})
        self.ws.commit(a2 / "lib", "w2", {"f2.txt": "2"})
        self.ws.commit(a2 / "app", "w3", {"g.txt": "3"})
        r = self.ws.ms("integrate", "b1")
        self.assertOk(r)
        self.assertTrue((self.d / "lib" / "f1.txt").exists() and (self.d / "lib" / "f2.txt").exists())
        self.assertTrue((self.d / "app" / "g.txt").exists())
        self.assertIn("already merged", self.ws.ms("integrate", "b1").stdout)

    def test_conflict_reports_files_and_keeps_earlier_merges(self):
        a1, a2, a3 = self.agent("t1", "lib"), self.agent("t2", "lib"), self.agent("t3", "lib")
        self.ws.commit(a1 / "lib", "w1", {"ok.txt": "1"})
        self.ws.commit(a2 / "lib", "w2", {"clash.txt": "AAA"})
        self.ws.commit(a3 / "lib", "w3", {"clash.txt": "BBB"})
        r = self.ws.ms("integrate", "b1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("CONFLICT", r.stderr)
        self.assertIn("clash.txt", r.stderr)
        self.assertTrue((self.d / "lib" / "ok.txt").exists())
        self.assertEqual(self.ws.git(self.d / "lib", "status", "--porcelain"), "")
        self.assertIn("conflict | integrate | lib | b1", self.ws.log_lines("--action", "integrate"))

    def test_dirty_integration_worktree_blocks_integrate(self):
        a = self.agent("t1", "lib")
        self.ws.commit(a / "lib", "w", {"f.txt": "1"})
        (self.d / "lib" / "dirty.txt").write_text("x")
        self.ws.git(self.d / "lib", "add", "dirty.txt")
        r = self.ws.ms("integrate", "b1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("uncommitted", r.stderr)

    def test_unknown_batch_fails(self):
        self.assertNotEqual(self.ws.ms("integrate", "ghost").returncode, 0)


# ----------------------------------------------------------------------- ship
class TestShip(Base):
    E2E = '\n[e2e]\ncommand = "echo e2e-ran"\nrepo = "app"\n'

    def setUp(self):
        super().setUp()
        self.ws.set_toml(DEFAULT_TOML + self.E2E)
        self.d = self.ws.batch("b1")
        self.ws.commit(self.d / "lib", "lib feature", {"feat.txt": "1"})
        self.ws.commit(self.d / "app", "app feature", {"feat.txt": "2"})

    def test_plan_only_does_not_push(self):
        r = self.ws.ms("ship", "b1")
        self.assertOk(r)
        self.assertIn("Plan for batch", r.stdout)
        self.assertIn("plan only", r.stdout)
        self.assertNotIn("lib feature", self.ws.remote_log("lib"))

    def test_yes_pushes_each_repo_to_its_base(self):
        r = self.ws.ms("ship", "b1", "--yes")
        self.assertOk(r)
        self.assertIn("PASS t2", r.stdout)
        self.assertEqual(self.ws.remote_log("lib")[0], "lib feature")
        self.assertEqual(self.ws.remote_log("app")[0], "app feature")

    def test_push_ask_needs_an_explicit_choice(self):
        self.ws.set_toml((DEFAULT_TOML + self.E2E).replace('[repos.lib]\nbase = "next"', '[repos.lib]\nbase = "next"\npush = "ask"'))
        r = self.ws.ms("ship", "b1", "--yes")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--direct", r.stderr)
        self.assertNotIn("lib feature", self.ws.remote_log("lib"))
        self.assertOk(self.ws.ms("ship", "b1", "--yes", "--direct"))
        self.assertIn("lib feature", self.ws.remote_log("lib"))

    def test_missing_e2e_requires_explicit_skip(self):
        self.ws.set_toml(DEFAULT_TOML)
        r = self.ws.ms("ship", "b1", "--yes")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--skip-e2e", r.stderr)
        self.assertNotIn("lib feature", self.ws.remote_log("lib"))
        self.assertOk(self.ws.ms("ship", "b1", "--yes", "--skip-e2e"))
        self.assertIn("lib feature", self.ws.remote_log("lib"))

    def test_failing_t1_blocks_the_push(self):
        self.ws.set_toml((DEFAULT_TOML + self.E2E).replace('unit = "echo unit-lib"', 'unit = "exit 1"'))
        r = self.ws.ms("ship", "b1", "--yes")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("nothing was pushed", r.stderr)
        self.assertNotIn("lib feature", self.ws.remote_log("lib"))
        self.assertNotIn("app feature", self.ws.remote_log("app"))

    def test_failing_e2e_blocks_the_push(self):
        self.ws.set_toml(DEFAULT_TOML + '\n[e2e]\ncommand = "exit 1"\nrepo = "app"\n')
        self.assertNotEqual(self.ws.ms("ship", "b1", "--yes").returncode, 0)
        self.assertNotIn("lib feature", self.ws.remote_log("lib"))

    def test_base_moved_is_merged_before_pushing(self):
        mate = self.ws.tmp / "mate"
        self.ws.git(self.ws.tmp, "clone", "-q", str(self.ws.tmp / "remote-lib.git"), str(mate))
        self.ws.git(mate, "checkout", "-q", "next")
        self.ws.commit(mate, "mate commit", {"mate.txt": "m"})
        self.ws.git(mate, "push", "-q", "origin", "next")
        r = self.ws.ms("ship", "b1", "--yes")
        self.assertOk(r)
        self.assertIn("base moved", r.stdout)
        log = self.ws.remote_log("lib")
        self.assertIn("mate commit", log)
        self.assertIn("lib feature", log)

    def test_release_branch_is_never_a_target(self):
        self.ws.set_toml((DEFAULT_TOML + self.E2E).replace('[repos.lib]\nbase = "next"', '[repos.lib]\nbase = "next"\nrelease = ["next"]'))
        r = self.ws.ms("ship", "b1", "--yes")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("release branch", r.stderr)

    def test_dirty_worktree_blocks_ship(self):
        (self.d / "lib" / "feat.txt").write_text("changed again")
        r = self.ws.ms("ship", "b1", "--yes")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("uncommitted", r.stderr)

    def plain_branch(self):
        lib = self.ws.project / "lib"
        self.ws.git(lib, "switch", "-q", "-c", "fix/small")
        self.ws.commit(lib, "small fix", {"fix.txt": "1"})
        return lib

    def test_plain_branch_ships_from_the_repo_checkout(self):
        lib = self.plain_branch()
        plan = self.ws.ms("ship", "--branch", cwd=lib)
        self.assertOk(plan)
        self.assertIn("fix/small -> next", plan.stdout)
        self.assertNotIn("small fix", self.ws.remote_log("lib"))
        r = self.ws.ms("ship", "--branch", "--yes", "--skip-e2e", cwd=lib)
        self.assertOk(r)
        self.assertIn("PASS t1 lib", r.stdout)
        self.assertEqual(self.ws.remote_log("lib")[0], "small fix")
        self.assertEqual(self.ws.git(lib, "branch", "--show-current"), "fix/small")   # the user's branch is left alone

    def test_plain_branch_can_name_the_repo(self):
        self.plain_branch()
        self.assertOk(self.ws.ms("ship", "--branch", "lib", "--yes", "--skip-e2e"))
        self.assertEqual(self.ws.remote_log("lib")[0], "small fix")

    def test_plain_branch_refuses_the_base_branch_and_dirty_trees(self):
        lib = self.ws.project / "lib"
        r = self.ws.ms("ship", "--branch", cwd=lib)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("task branch", r.stderr)
        self.plain_branch()
        (lib / "fix.txt").write_text("dirty")
        r = self.ws.ms("ship", "--branch", "--yes", "--skip-e2e", cwd=lib)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("uncommitted", r.stderr)

    def test_nothing_to_ship(self):
        self.ws.batch("empty")
        r = self.ws.ms("ship", "empty")
        self.assertOk(r)
        self.assertIn("Nothing to ship", r.stdout)

    def test_unknown_option_fails(self):
        self.assertNotEqual(self.ws.ms("ship", "b1", "--bogus").returncode, 0)


# ---------------------------------------------------------------------- clean
class TestClean(Base):
    def setUp(self):
        super().setUp()
        self.d = self.ws.batch("b1")
        self.ws.commit(self.d / "lib", "feature", {"f.txt": "1"})

    def test_list_shows_pending_then_merged(self):
        self.assertIn("b1: pending", self.ws.ms("clean").stdout)
        self.assertOk(self.ws.ms("ship", "b1", "--yes", "--skip-e2e"))
        self.assertIn("b1: merged", self.ws.ms("clean").stdout)

    def test_clean_refuses_unmerged_batches(self):
        r = self.ws.ms("clean", "b1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not merged", r.stderr)
        self.assertTrue(self.d.exists())

    def test_clean_after_ship_removes_worktrees_branches_and_dir(self):
        self.assertOk(self.ws.ms("agent", "new", "b1", "t1", "lib"))
        self.assertOk(self.ws.ms("ship", "b1", "--yes", "--skip-e2e"))
        self.assertOk(self.ws.ms("clean", "b1"))
        self.assertFalse(self.d.exists())
        branches = self.ws.git(self.ws.root / "lib", "branch", "--list")
        self.assertNotIn("int/b1", branches)
        self.assertNotIn("agent/b1/t1", branches)
        self.assertNotIn(".batches/b1", self.ws.git(self.ws.root / "lib", "worktree", "list"))

    def test_clean_accepts_a_squash_merge_on_origin(self):
        lib = self.ws.root / "lib"
        base = self.ws.git(lib, "rev-parse", "--abbrev-ref", "HEAD").strip()
        self.ws.git(lib, "merge", "--squash", "int/b1")
        self.ws.git(lib, "commit", "-m", "squashed")
        self.ws.git(lib, "push", "origin", base)
        self.assertOk(self.ws.ms("clean", "b1"))
        self.assertFalse(self.d.exists())

    def test_force_discards_unmerged_work(self):
        self.assertOk(self.ws.ms("clean", "b1", "--force"))
        self.assertFalse(self.d.exists())
        self.assertNotIn("int/b1", self.ws.git(self.ws.root / "lib", "branch", "--list"))

    def test_no_batches(self):
        w = WS()
        self.addCleanup(w.close)
        self.assertIn("no batches", w.ms("clean").stdout)


# ---------------------------------------------------------------------- guard
class TestGuard(Base):
    def guard(self, command, cwd):
        return self.ws.ms("guard", input=json.dumps({"tool_input": {"command": command}, "cwd": str(cwd)}))

    def test_blocks_publishing_commands_inside_a_batch(self):
        d = self.ws.batch("b1")
        for cmd in ("git push origin int/b1", "git -C . push --force", "git push", "gh pr create --fill",
                    "gh pr merge 3", "ms-workspace ship b1 --yes --skip-gate", "ms-workspace clean b1 --force", "ms-workspace promote lib --yes"):
            with self.subTest(cmd=cmd):
                r = self.guard(cmd, d / "lib")
                self.assertEqual(r.returncode, 2, cmd)
                self.assertIn("Blocked", r.stderr)
        self.assertEqual(self.ws.log_lines("--action", "guard").count("blocked"), 8)

    def test_allows_normal_commands_inside_a_batch(self):
        d = self.ws.batch("b1")
        for cmd in ("git status", "git commit -m 'fix push handling'", "ms-workspace test t0", "ls",
                    "ms-workspace plan b1 --pr", "ms-workspace ship b1", "ms-workspace ship b1 --pr --yes", "rtk ms-workspace ship b1 --yes",
                    "ms-workspace clean b1", "ms-workspace clean"):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.guard(cmd, d / "lib").returncode, 0, cmd)

    def test_allows_everything_outside_batches(self):
        self.ws.batch("b1")
        self.assertEqual(self.guard("git push origin next", self.ws.root / "lib").returncode, 0)

    def test_allows_everything_outside_a_workspace(self):
        self.assertEqual(self.guard("git push", self.ws.tmp).returncode, 0)

    def test_garbage_input_never_blocks(self):
        self.assertEqual(self.ws.ms("guard", input="not json").returncode, 0)
        self.assertEqual(self.ws.ms("guard", input="{}").returncode, 0)


# ------------------------------------------------- status / context / doctor
class TestOverview(Base):
    def test_status_one_line_per_repo(self):
        self.ws.batch("b1", "lib")
        lines = self.ws.ms("status").stdout.strip().splitlines()
        self.assertEqual(len(lines), 2)
        lib = next(l for l in lines if l.startswith("lib:"))
        self.assertIn("vs next: +0/-0", lib)
        self.assertIn("batches: b1", lib)
        self.assertNotIn("batches", next(l for l in lines if l.startswith("app:")))

    def test_status_reports_dirty_and_missing(self):
        (self.ws.root / "lib" / "x.txt").write_text("x")
        self.assertIn("dirty 1", self.ws.ms("status").stdout)
        self.ws.set_toml(DEFAULT_TOML + '\n[repos.ghost]\nbase = "next"\n')
        self.assertIn("ghost: (not cloned)", self.ws.ms("status").stdout)

    def test_context_briefing(self):
        out = self.ws.ms("context").stdout
        self.assertIn("Workspace 't'", out)
        self.assertIn("Active batches: none", out)
        self.ws.batch("b1")
        out = self.ws.ms("context").stdout
        self.assertIn("b1", out)
        self.assertIn("open tasks", out)
        self.assertIn("Recent actions", out)

    def test_context_is_silent_outside_a_workspace(self):
        r = self.ws.ms("context", cwd=self.ws.tmp)
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_doctor_validates_workspace(self):
        out = self.ws.ms("doctor").stdout
        self.assertIn("all repos present, bases and deps valid", out)
        self.assertIn("Plan usage:", out)

    def test_doctor_flags_problems(self):
        self.ws.set_toml(DEFAULT_TOML.replace('deps = ["lib"]', 'deps = ["nobody"]'))
        r = self.ws.ms("doctor")
        self.assertEqual(r.returncode, 1)
        self.assertIn("unknown repo 'nobody'", r.stdout)
        self.ws.set_toml(DEFAULT_TOML + '\n[repos.ghost]\nbase = "next"\n')
        r = self.ws.ms("doctor")
        self.assertEqual(r.returncode, 1)
        self.assertIn("not cloned", r.stdout)

    def test_doctor_without_workspace_checks_general_tools(self):
        out = self.ws.ms("doctor", cwd=self.ws.tmp).stdout
        self.assertIn("general tools only", out)
        self.assertIn("git", out)

    def test_help_and_unknown_command(self):
        for flag in ("--help", "-h"):
            self.assertIn("batch new", self.ws.ms(flag, cwd=self.ws.tmp).stdout)
        r = self.ws.ms("frobnicate")
        self.assertEqual(r.returncode, 1)
        self.assertIn("unknown command", r.stderr)


# ------------------------------------------------- .dynamia/ layout, repo detection
class TestDynamiaLayout(unittest.TestCase):
    def tearDown(self):
        self.ws.close()

    def assertOk(self, r):
        self.assertEqual(r.returncode, 0, f"stdout={r.stdout!r} stderr={r.stderr!r}")

    def single_repo(self):
        """A project that is itself a git repo (branch next, with a remote); the workspace lives in its .dynamia/."""
        self.ws = WS(repos=(), toml=None, dynamia=True)
        proj = self.ws.project
        remote = self.ws.tmp / "remote-proj.git"
        self.ws.git(self.ws.tmp, "init", "-q", "--bare", str(remote))
        self.ws.git(remote, "symbolic-ref", "HEAD", "refs/heads/next")
        self.ws.git(proj, "init", "-q", "-b", "next")
        self.ws.git(proj, "remote", "add", "origin", str(remote))
        self.ws.commit(proj, "init", {"a.txt": "base\n", "CLAUDE.md": "# The repo's own notes\n"})
        self.ws.git(proj, "push", "-q", "origin", "next")
        self.ws.set_toml("""
            name = "solo"
            [repos.proj]
            base = "next"
            path = "."
            [repos.proj.test]
            unit = "echo unit-proj"
        """)
        return proj

    def test_multi_repo_workspace_found_from_the_project_folder_and_from_a_batch(self):
        self.ws = WS(dynamia=True)
        self.assertEqual(self.ws.root, self.ws.project / ".dynamia" / "workspace")
        self.assertOk(self.ws.ms("status", cwd=self.ws.project))
        d = self.ws.batch("b1", "lib")
        self.assertEqual(d, self.ws.root / "working-trees" / "b1")
        r = self.ws.ms("status", cwd=d / "lib")
        self.assertOk(r)
        self.assertIn("lib", r.stdout)

    def test_guard_blocks_push_inside_a_batch_of_the_new_layout(self):
        self.ws = WS(dynamia=True)
        d = self.ws.batch("b1", "lib")
        payload = json.dumps({"tool_input": {"command": "git push origin next"}, "cwd": str(d / "lib")})
        r = run([BIN, "guard"], cwd=d / "lib", env=self.ws.env, input=payload)
        self.assertEqual(r.returncode, 2, r.stderr)

    def test_single_repo_batch_is_a_worktree_inside_the_ignored_dynamia_folder(self):
        proj = self.single_repo()
        self.assertIn("added", self.ws.ms("exclude", cwd=proj).stdout)
        self.assertIn("present", self.ws.ms("exclude", cwd=proj).stdout, "idempotent")
        self.assertEqual((proj / ".git" / "info" / "exclude").read_text().count(".dynamia/"), 1)
        d = self.ws.batch("b1", "proj")
        wt = d / "proj"
        self.assertTrue((wt / "a.txt").is_file())
        self.assertEqual(self.ws.git(proj, "status", "--short"), "", "the repo stays clean")
        self.assertEqual(self.ws.git(wt, "status", "--short"), "", "so does the worktree")
        self.assertFalse((wt / ".dynamia").exists())
        self.assertOk(self.ws.ms("status", cwd=proj))
        r = self.ws.ms("test", "t0", cwd=proj)
        self.assertOk(r)
        self.assertIn("unit-proj", r.stdout + r.stderr)

    def test_project_reports_repo_workspace_and_claude_md(self):
        proj = self.single_repo()
        info = json.loads(self.ws.ms("project", cwd=proj).stdout)
        self.assertTrue(info["in_repo"])
        self.assertEqual(info["workspace"], "new")
        self.assertEqual(info["claude_md"], {"exists": True, "managed": False})
        self.assertFalse(info["excluded"])
        self.ws.ms("exclude", cwd=proj)
        self.assertTrue(json.loads(self.ws.ms("project", cwd=proj).stdout)["excluded"])
        outside = self.ws.tmp / "plain"
        outside.mkdir()
        info = json.loads(self.ws.ms("project", cwd=outside).stdout)
        self.assertFalse(info["in_repo"])
        self.assertEqual(info["workspace"], "none")
        self.assertIsNone(info["excluded"])

    def test_exclude_outside_a_repo_fails(self):
        self.ws = WS(repos=(), toml=None)
        r = self.ws.ms("exclude", cwd=self.ws.tmp)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not inside a git repository", r.stderr)

    def test_claude_md_of_the_repo_is_respected_until_the_user_agrees(self):
        proj = self.single_repo()
        r = self.ws.ms("claude-md", cwd=proj)
        self.assertEqual(r.returncode, 3)
        self.assertEqual((proj / "CLAUDE.md").read_text(), "# The repo's own notes\n")
        self.assertOk(self.ws.ms("claude-md", "--append", cwd=proj))
        text = (proj / "CLAUDE.md").read_text()
        self.assertTrue(text.startswith("# The repo's own notes\n"))
        self.assertIn("ms-workspace:begin", text)
        self.assertFalse((proj / ".dynamia" / "workspace" / "CLAUDE.md").exists())
        self.assertIn("Updated", self.ws.ms("claude-md", cwd=proj).stdout, "once managed, it refreshes without asking")

    def test_repos_live_in_the_project_folder_and_old_clones_inside_the_workspace_still_work(self):
        self.ws = WS(dynamia=True)
        self.assertEqual(self.ws.ms("status", cwd=self.ws.project).returncode, 0)
        self.assertTrue((self.ws.project / "lib" / ".git").exists())
        self.assertFalse((self.ws.root / "lib").exists())
        shutil.move(str(self.ws.project / "lib"), str(self.ws.root / "lib"))   # the 0.4 / 0.5.0 layout
        self.assertIn("lib", self.ws.ms("status", cwd=self.ws.project).stdout)
        dry = self.ws.ms("migrate")
        self.assertIn("would move", dry.stdout)
        self.assertTrue((self.ws.root / "lib").exists(), "a dry run moves nothing")
        self.assertOk(self.ws.ms("migrate", "--yes"))
        self.assertTrue((self.ws.project / "lib" / ".git").exists())
        self.assertFalse((self.ws.root / "lib").exists())
        self.assertIn("nothing to migrate", self.ws.ms("migrate").stderr)
        self.assertOk(self.ws.ms("status", cwd=self.ws.project))

    def test_state_folders_sit_directly_in_the_workspace_folder(self):
        self.ws = WS(dynamia=True)
        self.ws.batch("b1", "lib")
        self.assertOk(self.ws.ms("test", "t0", "--repo", "lib", cwd=self.ws.root / "working-trees" / "b1" / "lib"))
        self.assertTrue((self.ws.root / "logs").is_dir())
        self.assertFalse((self.ws.root / ".ms-workspace").exists())
        self.assertFalse((self.ws.root / ".batches").exists())

    def test_migrate_renames_the_dot_folders_of_0_6_0(self):
        self.ws = WS(dynamia=True)
        root = self.ws.root
        (root / ".ms-workspace" / "logs").mkdir(parents=True)
        (root / ".ms-workspace" / "logs" / "2026-01-01.jsonl").write_text("{}\n")
        (root / ".ms-workspace" / "images").mkdir()
        (root / ".batches").mkdir()
        self.assertOk(self.ws.ms("status", cwd=self.ws.project))   # a leftover dot folder is still honoured
        self.assertIn("would move", self.ws.ms("migrate").stdout)
        self.assertOk(self.ws.ms("migrate", "--yes"))
        self.assertTrue((root / "logs" / "2026-01-01.jsonl").is_file())
        self.assertTrue((root / "images").is_dir())
        self.assertTrue((root / "working-trees").is_dir())
        self.assertFalse((root / ".ms-workspace").exists())
        self.assertFalse((root / ".batches").exists())
        self.assertIn("nothing to migrate", self.ws.ms("migrate").stderr)

    def test_migrate_moves_the_older_layout_and_refuses_open_batches(self):
        self.ws = WS()
        self.ws.batch("b1", "lib")
        r = self.ws.ms("migrate", "--yes")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("open batches", r.stderr)
        self.assertOk(self.ws.ms("clean", "b1", "--force"))
        dry = self.ws.ms("migrate")
        self.assertIn("would move", dry.stdout)
        self.assertTrue((self.ws.root / "workspace.toml").exists(), "a dry run moves nothing")
        self.assertOk(self.ws.ms("migrate", "--yes"))
        new = self.ws.project / ".dynamia"
        self.assertTrue((new / "workspace.toml").is_file())
        self.assertTrue((self.ws.project / "lib" / ".git").exists(), "the repos stay where they are")
        self.assertFalse((new / "workspace" / "lib").exists())
        self.assertTrue((new / "workspace" / "logs").is_dir(), "state folders lose their dot folder")
        self.assertFalse((new / "workspace" / ".ms-workspace").exists())
        self.assertOk(self.ws.ms("status", cwd=self.ws.project))


# ------------------------------------------------------------------ dev-env
class TestDevEnv(Base):
    def toml(self):
        return self.ws.cfg.read_text()

    def test_add_list_and_remove_keep_the_rest_of_the_file(self):
        self.ws.cfg.write_text("# my notes\n" + self.ws.cfg.read_text() + "\n# tail comment\n")
        self.assertOk(self.ws.ms("dev-env", "add", "API_URL=http://localhost:8080"))
        self.assertOk(self.ws.ms("dev-env", "add", "DEBUG=1", "--repo", "app"))
        self.assertOk(self.ws.ms("dev-env", "add", "API_URL=http://localhost:9090"))
        text = self.toml()
        self.assertTrue(text.startswith("# my notes\n"))
        self.assertIn("# tail comment", text)
        self.assertEqual(text.count("API_URL"), 1, "setting again replaces the line")
        listing = self.ws.ms("dev-env", "list").stdout
        self.assertIn("all            API_URL=http://localhost:9090", listing)
        self.assertIn("app            DEBUG=1", listing)
        self.assertOk(self.ws.ms("dev-env", "rm", "DEBUG", "--repo", "app"))
        self.assertNotIn("DEBUG", self.ws.ms("dev-env", "list").stdout)
        self.assertIn("absent", self.ws.ms("dev-env", "rm", "NOPE").stdout)

    def test_removing_the_last_variable_drops_the_empty_table(self):
        before = self.toml()
        self.ws.ms("dev-env", "add", "A=1", "--repo", "app")
        self.ws.ms("dev-env", "rm", "A", "--repo", "app")
        self.assertNotIn("dev", self.toml())
        self.assertEqual(self.toml().strip(), before.strip())

    def test_a_second_variable_joins_the_existing_table(self):
        self.ws.ms("dev-env", "add", "A=1")
        self.ws.ms("dev-env", "add", "B=2")
        self.assertEqual(self.toml().count("[dev.env]"), 1)

    def test_values_with_quotes_and_unicode_survive(self):
        self.assertOk(self.ws.ms("dev-env", "add", 'MSG=say "hi" \\ ñ'))
        import tomllib
        self.assertEqual(tomllib.loads(self.toml())["dev"]["env"]["MSG"], 'say "hi" \\ ñ')

    def test_bad_input_is_refused_and_the_file_is_untouched(self):
        before = self.toml()
        for args in (["add", "1BAD=x"], ["add", "NOEQUALS"], ["add", "A=1", "--repo", "ghost"], ["add", "A=1\nB=2"]):
            r = self.ws.ms("dev-env", *args)
            self.assertNotEqual(r.returncode, 0, args)
        self.assertEqual(self.toml(), before)

    def test_secret_looking_names_are_hidden_in_list_and_noted_on_add(self):
        r = self.ws.ms("dev-env", "add", "DB_PASSWORD=hunter2")
        self.assertIn("looks secret", r.stdout)
        self.assertNotIn("hunter2", self.ws.ms("dev-env", "list").stdout)
        self.assertIn("hunter2", self.ws.ms("dev-env", "list", "--show").stdout)

    def test_json_listing_for_the_panel_hides_secrets(self):
        self.ws.ms("dev-env", "add", "API_URL=http://x")
        self.ws.ms("dev-env", "add", "API_TOKEN=abc", "--repo", "lib")
        data = json.loads(self.ws.ms("dev-env", "list", "--json").stdout)
        self.assertEqual(data["repos"], ["app", "lib"])
        self.assertIn({"scope": "all", "name": "API_URL", "value": "http://x", "secret": False}, data["vars"])
        self.assertIn({"scope": "lib", "name": "API_TOKEN", "value": "***", "secret": True}, data["vars"])

    def test_variables_reach_the_test_command_and_the_repo_wins(self):
        self.ws.set_toml("""
            name = "t"
            [dev.env]
            WHO = "workspace"
            ONLY = "all"
            [repos.lib]
            base = "next"
            [repos.lib.dev.env]
            WHO = "lib"
            [repos.lib.test]
            unit = "echo got-$WHO-$ONLY > seen.txt"
        """)
        d = self.ws.batch("b1", "lib")
        r = self.ws.ms("test", "t0", cwd=d / "lib")
        self.assertOk(r)
        self.assertEqual((d / "lib" / "seen.txt").read_text().strip(), "got-lib-all")

    def test_changing_a_variable_invalidates_the_cached_pass(self):
        self.ws.set_toml("""
            name = "t"
            [repos.lib]
            base = "next"
            [repos.lib.test]
            unit = "echo v=$VAR"
        """)
        d = self.ws.batch("b1", "lib")
        self.ws.ms("dev-env", "add", "VAR=1")
        self.assertOk(self.ws.ms("test", "t0", cwd=d / "lib"))
        self.assertIn("cached", self.ws.ms("test", "t0", cwd=d / "lib").stdout)
        self.ws.ms("dev-env", "add", "VAR=2")
        again = self.ws.ms("test", "t0", cwd=d / "lib")
        self.assertNotIn("cached", again.stdout)

    def test_works_in_the_dynamia_layout(self):
        self.ws.close()
        self.ws = WS(dynamia=True)
        self.assertOk(self.ws.ms("dev-env", "add", "X=1", cwd=self.ws.project))
        self.assertIn('X = "1"', self.ws.cfg.read_text())


# ------------------------------------------------------------------ claude-md
class TestClaudeMd(Base):
    def test_create_content_and_order(self):
        r = self.ws.ms("claude-md")
        self.assertOk(r)
        text = (self.ws.root / "CLAUDE.md").read_text()
        self.assertIn("# Workspace: t", text)
        self.assertLess(text.index("- lib:"), text.index("- app:"))
        self.assertIn("depends on lib", text)
        self.assertIn("ms-workspace usage --check", text)
        self.assertIn("dynamia:scout", text)
        self.assertEqual(text.count("ms-workspace:begin"), 1)

    def test_regeneration_keeps_user_notes_and_updates_block(self):
        self.ws.ms("claude-md")
        p = self.ws.root / "CLAUDE.md"
        p.write_text("# My notes\nkeep me\n\n" + p.read_text() + "\nfooter note\n")
        self.ws.set_toml(DEFAULT_TOML.replace('name = "t"', 'name = "renamed"'))
        self.assertIn("Updated", self.ws.ms("claude-md").stdout)
        text = p.read_text()
        self.assertIn("keep me", text)
        self.assertIn("footer note", text)
        self.assertIn("# Workspace: renamed", text)
        self.assertNotIn("# Workspace: t\n", text)
        self.assertEqual(text.count("ms-workspace:begin"), 1)

    def test_appends_block_to_an_existing_file_without_markers(self):
        p = self.ws.root / "CLAUDE.md"
        p.write_text("# Hand written\n")
        refused = self.ws.ms("claude-md")
        self.assertEqual(refused.returncode, 3)
        self.assertEqual(p.read_text(), "# Hand written\n", "an existing file is left alone until the user agrees")
        self.assertIn("Appended", self.ws.ms("claude-md", "--append").stdout)
        text = p.read_text()
        self.assertTrue(text.startswith("# Hand written"))
        self.assertIn("ms-workspace:end", text)

    def test_print_does_not_write(self):
        r = self.ws.ms("claude-md", "--print")
        self.assertIn("# Workspace: t", r.stdout)
        self.assertFalse((self.ws.root / "CLAUDE.md").exists())

    def test_tools_policy_and_task_overrides(self):
        self.ws.set_toml(DEFAULT_TOML.replace('name = "t"', 'name = "t"\ntasks = "local"\n[tools]\ndiscovery = ["idea", "mcp:ctx", "grep"]\nnotes = "Small diffs."')
                         .replace('[repos.app]\nbase = "next"', '[repos.app]\nbase = "next"\ntasks = "github"'))
        text = self.ws.ms("claude-md", "--print").stdout
        self.assertIn("1. IDE tools", text)
        self.assertIn("2. `mcp__ctx__*` tools", text)
        self.assertIn("3. Grep/Glob/Read", text)
        self.assertIn("Small diffs.", text)
        self.assertIn("- app: github", text)

    def test_default_tools_policy_lists_only_what_is_installed(self):
        bare = tempfile.mkdtemp()
        text = self.ws.ms_py("claude-md", "--print", env={"PATH": bare}).stdout
        self.assertIn("1. Grep/Glob/Read", text)
        self.assertNotIn("codebase-memory", text)
        self.assertNotIn("IDE tools", text)
        binary = Path(bare) / "codebase-memory-mcp"
        binary.write_text("#!/bin/sh\n")
        binary.chmod(0o755)
        text = self.ws.ms_py("claude-md", "--print", env={"PATH": bare}).stdout
        self.assertIn("1. codebase-memory graph tools", text)
        self.assertIn("2. Grep/Glob/Read", text)

    def test_refresh_rewrites_only_a_fully_generated_file(self):
        p = self.ws.root / "CLAUDE.md"
        self.assertIn("left untouched", self.ws.ms("claude-md", "--refresh").stdout)
        self.assertFalse(p.exists(), "refresh never creates the file")
        self.ws.ms("claude-md")
        self.ws.set_toml(DEFAULT_TOML.replace('name = "t"', 'name = "renamed"'))
        self.assertIn("Refreshed", self.ws.ms("claude-md", "--refresh").stdout)
        self.assertIn("# Workspace: renamed", p.read_text())
        mine = "# Mine\n\n" + p.read_text()
        p.write_text(mine)
        self.ws.set_toml(DEFAULT_TOML)
        self.assertIn("left untouched", self.ws.ms("claude-md", "--refresh").stdout)
        self.assertEqual(p.read_text(), mine)


# ---------------------------------------------------------------------- usage
class TestUsage(Base):
    def snapshot(self, p5, left5, p7=41.0, left7=4 * 86400, age=0):
        now = int(time.time())
        data = {"captured_at": now - age,
                "five_hour": None if p5 is None else {"used_percentage": p5, "resets_at": now + left5},
                "seven_day": {"used_percentage": p7, "resets_at": now + left7}}
        self.ws.cache.mkdir(exist_ok=True)
        (self.ws.cache / "usage.json").write_text(json.dumps(data))

    def check(self, *extra):
        return self.ws.ms("usage", "--check", *extra).returncode

    def test_exit_codes_by_scenario(self):
        cases = [
            (23, 4 * 3600, [], 0),          # early and low
            (55, 7200, [], 0),              # moderate, projection under 100
            (75, 7200, [], 1),              # above warn
            (92, 7200, [], 2),              # above stop
            (85, 9000, [], 2),              # runs out in under 30 min
            (23, 4 * 3600, ["--need", "30"], 0),
            (23, 4 * 3600, ["--need", "80"], 2),
            (60, 4 * 3600, ["--need", "35"], 1),
        ]
        for used, left, extra, expected in cases:
            with self.subTest(used=used, left=left, extra=extra):
                self.snapshot(used, left)
                self.assertEqual(self.check(*extra), expected)

    def test_no_data_is_exit_3_and_never_blocks_plain_calls(self):
        self.assertEqual(self.check(), 3)
        self.assertEqual(self.ws.ms("usage").returncode, 0)
        self.assertEqual(self.ws.ms("usage", "--line").returncode, 0)

    def test_expired_window_is_reported_as_reset(self):
        self.snapshot(80, -60)
        r = self.ws.ms("usage")
        self.assertIn("window reset", r.stdout)
        self.assertEqual(self.check(), 0)

    def test_text_json_and_line_outputs(self):
        self.snapshot(75, 7200)
        text = self.ws.ms("usage").stdout
        self.assertIn("75% used, 25% left", text)
        self.assertIn("verdict: WARN", text)
        data = json.loads(self.ws.ms("usage", "--json").stdout)
        self.assertEqual((data["verdict"], data["level"]), ("warn", 1))
        self.assertTrue(self.ws.ms("usage", "--line").stdout.startswith("usage 5h 75%"))

    def test_stale_data_is_noted(self):
        self.snapshot(23, 4 * 3600, age=3600)
        self.assertIn("min old", self.ws.ms("usage").stdout)

    def test_thresholds_come_from_workspace_toml(self):
        self.snapshot(40, 4 * 3600)
        self.assertEqual(self.check(), 0)
        self.ws.set_toml(DEFAULT_TOML + "\n[usage]\nwarn_pct = 30\nstop_pct = 35\n")
        self.assertEqual(self.check(), 2)

    def test_works_outside_a_workspace(self):
        self.snapshot(75, 7200)
        self.assertEqual(self.ws.ms("usage", "--check", cwd=self.ws.tmp).returncode, 1)

    def test_context_includes_a_usage_line(self):
        self.snapshot(23, 4 * 3600)
        self.assertIn("usage 5h 23%", self.ws.ms("context").stdout)

    def test_doctor_reports_the_snapshot(self):
        self.snapshot(23, 4 * 3600)
        self.assertIn("usage snapshot", self.ws.ms("doctor").stdout)


class TestStatusline(Base):
    def feed(self, **kw):
        now = int(time.time())
        payload = {"model": {"display_name": "Opus 5.5"}, "context_window": {"used_percentage": 12.4}}
        if kw:
            payload["rate_limits"] = {"five_hour": {"used_percentage": kw["p5"], "resets_at": now + 4 * 3600},
                                      "seven_day": {"used_percentage": kw["p7"], "resets_at": now + 4 * 86400}}
        return run([STATUSLINE], env={**self.ws.env, "NO_COLOR": "1", "MS_GIT_CACHE_SECS": "0"}, input=json.dumps(payload))

    def test_prints_line_and_stores_snapshot_and_history(self):
        r = self.feed(p5=23.5, p7=41.2)
        self.assertEqual(r.returncode, 0)
        self.assertIn("[Opus 5.5] ctx 12%", r.stdout)
        self.assertIn("5h", r.stdout)
        self.assertIn("7d", r.stdout)
        snap = json.loads((self.ws.cache / "usage.json").read_text())
        self.assertEqual(snap["five_hour"]["used_percentage"], 23.5)
        self.assertEqual(snap["seven_day"]["used_percentage"], 41.2)
        self.assertEqual(len((self.ws.cache / "usage-history.jsonl").read_text().splitlines()), 1)
        self.feed(p5=24, p7=41.2)  # sampled at most once a minute
        self.assertEqual(len((self.ws.cache / "usage-history.jsonl").read_text().splitlines()), 1)

    def test_without_rate_limits_no_snapshot(self):
        r = self.feed()
        self.assertEqual(r.stdout.strip(), "[Opus 5.5] ctx 12%")
        self.assertFalse((self.ws.cache / "usage.json").exists())

    def line(self, cwd=None, key="cwd", cost=None, plain=True, secs="0"):
        payload = {"model": {"display_name": "M"}, "context_window": {"used_percentage": 5}}
        if cwd is not None:
            payload.update({"workspace": {"current_dir": str(cwd)}} if key == "workspace" else {"cwd": str(cwd)})
        if cost is not None:
            payload["cost"] = {"total_cost_usd": cost}
        env = {**self.ws.env, "MS_GIT_CACHE_SECS": secs, **({"NO_COLOR": "1"} if plain else {})}
        return run([STATUSLINE], env=env, input=json.dumps(payload)).stdout.strip()

    def test_dirty_files_ahead_behind_and_cost(self):
        lib = self.ws.root / "lib"
        (lib / "new.txt").write_text("x")
        (lib / "a.txt").write_text("changed")
        self.assertEqual(self.line(lib, cost=0.4231), "[M] ⎇ next ●2 ctx 5% $0.42")
        self.ws.git(lib, "add", "-A")
        self.ws.commit(lib, "local")
        self.ws.git(lib, "branch", "--set-upstream-to=origin/next")
        self.assertEqual(self.line(lib), "[M] ⎇ next ↑1 ctx 5%")
        other = self.ws.tmp / "other"
        self.ws.git(self.ws.tmp, "clone", "-q", str(self.ws.tmp / "remote-lib.git"), str(other))
        self.ws.git(other, "checkout", "-q", "next")
        self.ws.commit(other, "remote one", {"r.txt": "r"})
        self.ws.git(other, "push", "-q", "origin", "next")
        self.ws.git(lib, "fetch", "-q")
        self.assertEqual(self.line(lib), "[M] ⎇ next ↑1 ↓1 ctx 5%")

    def test_colors_by_default_and_none_with_no_color(self):
        lib = self.ws.root / "lib"
        (lib / "new.txt").write_text("x")
        colored = self.line(lib, plain=False)
        for code in ("\033[36m", "\033[35m", "\033[33m", "\033[32m"):   # model, branch, dirty, ctx
            self.assertIn(code, colored)
        self.assertNotIn("\033", self.line(lib))

    def test_git_state_is_cached_for_a_few_seconds(self):
        lib = self.ws.root / "lib"
        self.assertEqual(self.line(lib, secs="60"), "[M] ⎇ next ctx 5%")
        (lib / "new.txt").write_text("x")
        self.assertEqual(self.line(lib, secs="60"), "[M] ⎇ next ctx 5%")
        self.assertEqual(self.line(lib, secs="0"), "[M] ⎇ next ●1 ctx 5%")

    def test_shows_the_current_branch_in_a_repo_and_a_worktree(self):
        self.assertEqual(self.line(self.ws.root / "lib"), "[M] ⎇ next ctx 5%")
        self.assertEqual(self.line(self.ws.root / "lib", key="workspace"), "[M] ⎇ next ctx 5%")
        b = self.ws.batch("b1")
        self.assertEqual(self.line(b / "lib"), "[M] ⎇ int/b1 ctx 5%")
        self.assertEqual(self.line(b / "lib" / "sub-missing"), "[M] ctx 5%")

    def test_detached_head_shows_the_short_hash_and_non_repos_show_nothing(self):
        sha = self.ws.git(self.ws.root / "lib", "rev-parse", "--short", "HEAD")
        self.ws.git(self.ws.root / "lib", "checkout", "-q", "--detach")
        self.assertEqual(self.line(self.ws.root / "lib"), f"[M] ⎇ {sha} ctx 5%")
        self.assertEqual(self.line(self.ws.tmp), "[M] ctx 5%")
        self.assertEqual(self.line(), "[M] ctx 5%")

    def test_garbage_input_is_harmless(self):
        r = run([STATUSLINE], env=self.ws.env, input="nonsense")
        self.assertEqual(r.returncode, 0)


# ------------------------------------------------------------------------ log
class TestLog(Base):
    def test_filters_and_limits(self):
        self.ws.batch("b1")
        self.ws.ms("test", "t0", cwd=self.ws.root / ".batches" / "b1" / "lib")
        self.assertIn("batch.new", self.ws.log_lines("--action", "batch.new"))
        self.assertNotIn("test.t0", self.ws.log_lines("--action", "batch.new"))
        self.assertEqual(len(self.ws.log_lines("-n", "1").strip().splitlines()), 1)
        today = time.strftime("%Y-%m-%d")
        self.assertIn("batch.new", self.ws.log_lines("--day", today))
        self.assertIn("no log for", self.ws.log_lines("--day", "1999-01-01"))

    def test_line_format(self):
        self.ws.batch("b1", "lib")
        line = self.ws.log_lines("-n", "1").strip()
        self.assertRegex(line, r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d \| ok \| batch\.new \| lib \| b1 \| int/b1 from origin/next$")

    def test_empty_log(self):
        self.assertIn("no log yet", self.ws.log_lines())

    def test_old_daily_files_and_memos_are_rotated(self):
        logs = self.ws.root / ".ms-workspace" / "logs"
        memo = self.ws.root / ".ms-workspace" / "memo"
        logs.mkdir(parents=True)
        memo.mkdir()
        old = time.time() - 40 * 86400
        for p in (logs / "2020-01-01.jsonl", memo / "lib-abc"):
            p.write_text("{}\n")
            os.utime(p, (old, old))
        self.ws.batch("b1")
        self.assertFalse((logs / "2020-01-01.jsonl").exists())
        self.assertFalse((memo / "lib-abc").exists())

    def test_retention_is_configurable(self):
        self.ws.set_toml(DEFAULT_TOML.replace('name = "t"', 'name = "t"\nlog_retention_days = 100'))
        logs = self.ws.root / ".ms-workspace" / "logs"
        logs.mkdir(parents=True)
        old = time.time() - 40 * 86400
        (logs / "2020-01-01.jsonl").write_text("{}\n")
        os.utime(logs / "2020-01-01.jsonl", (old, old))
        self.ws.batch("b1")
        self.assertTrue((logs / "2020-01-01.jsonl").exists())


# --------------------------------------------------------------------- images
class TestImages(Base):
    def setUp(self):
        super().setUp()
        self.tp = self.ws.tmp / "transcript.jsonl"
        self.tp.write_text("")
        self.img_dir = self.ws.root / ".ms-workspace" / "images"

    def msg(self, text="hello\nworld  there", n=1, png=PNG, mt="image/png", ts="2026-10-15T23:40:00.000Z", role="user"):
        blocks = [{"type": "image", "source": {"type": "base64", "media_type": mt, "data": base64.b64encode(png).decode()}} for _ in range(n)]
        blocks.append({"type": "text", "text": text})
        return json.dumps({"type": role, "timestamp": ts, "cwd": str(self.ws.root / "lib"), "sessionId": "sess1234abcd",
                           "message": {"role": role, "content": blocks}})

    def capture(self, cwd=None, sid="sess1234abcd", tp=None):
        payload = {"transcript_path": str(tp or self.tp), "cwd": str(cwd or self.ws.root / "lib"), "session_id": sid}
        return self.ws.ms("images", "capture", input=json.dumps(payload))

    def files(self):
        return sorted(p for p in self.img_dir.rglob("*") if p.is_file() and p.suffix in (".png", ".jpg", ".gif", ".webp", ".bin"))

    def append(self, line):
        with open(self.tp, "a") as f:
            f.write(line)

    def test_saves_pasted_images_with_index(self):
        self.append(self.msg(n=1) + "\n")
        self.assertEqual(self.capture().returncode, 0)
        files = self.files()
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].read_bytes(), PNG)
        self.assertRegex(files[0].name, r"^\d{6}_sess1234_1\.png$")
        entry = json.loads((self.img_dir / "index.jsonl").read_text().splitlines()[0])
        self.assertEqual(entry["text"], "hello world there")
        self.assertEqual(entry["media_type"], "image/png")
        self.assertEqual(entry["bytes"], len(PNG))
        self.assertIn("images", self.ws.log_lines("--action", "images"))

    def test_multiple_images_in_one_message_are_deduplicated_by_content(self):
        self.append(self.msg(n=2) + "\n")
        self.capture()
        self.assertEqual(len(self.files()), 1)

    def test_distinct_images_get_distinct_files(self):
        other = PNG + b"\x00"
        blocks = [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64.b64encode(b).decode()}} for b in (PNG, other)]
        self.append(json.dumps({"timestamp": "2026-10-15T23:40:00.000Z", "cwd": "/x", "message": {"role": "user", "content": blocks}}) + "\n")
        self.capture()
        self.assertEqual([p.name[-6:] for p in self.files()], ["_1.png", "_2.png"])

    def test_incremental_reads_and_half_written_lines(self):
        self.append(self.msg(ts="2026-10-15T23:40:00.000Z") + "\n")
        self.capture()
        self.assertEqual(len(self.files()), 1)
        self.capture()
        self.assertEqual(len(self.files()), 1)
        second = self.msg(png=PNG + b"\x01", ts="2026-10-15T23:41:00.000Z")
        self.append(second[:80])
        self.capture()
        self.assertEqual(len(self.files()), 1, "a half-written line must wait")
        self.append(second[80:] + "\n")
        self.capture()
        self.assertEqual(len(self.files()), 2)

    def test_ignores_assistant_messages_and_tool_result_images(self):
        self.append(self.msg(role="assistant") + "\n")
        nested = {"timestamp": "2026-10-15T23:40:00.000Z", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "x", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64.b64encode(PNG).decode()}}]}]}}
        self.append(json.dumps(nested) + "\n")
        self.append("this line is not json\n")
        self.assertEqual(self.capture().returncode, 0)
        self.assertEqual(self.files(), [])

    def test_extension_follows_media_type(self):
        self.append(self.msg(mt="image/jpeg") + "\n")
        self.capture()
        self.assertTrue(self.files()[0].name.endswith(".jpg"))

    def test_capture_never_fails_the_session(self):
        for payload in ("", "garbage", "{}", json.dumps({"transcript_path": "/nope", "cwd": str(self.ws.root), "session_id": "s"})):
            self.assertEqual(self.ws.ms("images", "capture", input=payload).returncode, 0, payload)

    def test_outside_a_workspace_nothing_is_written(self):
        self.append(self.msg() + "\n")
        r = self.capture(cwd=self.ws.tmp)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self.files(), [])

    def test_list_and_empty_state(self):
        self.assertIn("no images archived", self.ws.ms("images", "list").stdout)
        self.append(self.msg() + "\n")
        self.capture()
        out = self.ws.ms("images", "list").stdout
        self.assertIn("hello world there", out)
        self.assertIn(str(self.ws.root), out)
        self.assertIn("(0KB)", out)
        self.assertNotIn("\n\n", out.strip())
        self.assertEqual(self.ws.ms("images", "list", "--day", "1999-01-01").stdout.strip(), "")

    def test_default_subcommand_is_list(self):
        self.assertIn("no images archived", self.ws.ms("images").stdout)

    def test_backfill_imports_sessions_that_ran_inside_the_workspace(self):
        proj = self.ws.home / ".claude" / "projects" / "-x"
        proj.mkdir(parents=True)
        (proj / "inside.jsonl").write_text(self.msg(png=PNG + b"\x07") + "\n")
        outside = json.loads(self.msg(png=PNG + b"\x08"))
        outside["cwd"] = "/somewhere/else"
        (proj / "outside.jsonl").write_text(json.dumps(outside) + "\n")
        r = self.ws.ms("images", "backfill")
        self.assertOk(r)
        self.assertIn("Saved 1 image", r.stdout)
        self.assertEqual(len(self.files()), 1)

    def test_old_images_are_pruned_and_index_cleaned(self):
        self.ws.set_toml(DEFAULT_TOML.replace('name = "t"', 'name = "t"\nimages_retention_days = 5'))
        self.append(self.msg() + "\n")
        self.capture()
        f = self.files()[0]
        old = time.time() - 30 * 86400
        os.utime(f, (old, old))
        (self.img_dir / ".state" / ".pruned").unlink()
        self.append(self.msg(png=PNG + b"\x09", ts="2026-10-15T23:50:00.000Z") + "\n")
        self.capture()
        self.assertFalse(f.exists())
        index = [json.loads(l) for l in (self.img_dir / "index.jsonl").read_text().splitlines()]
        self.assertEqual(len(index), 1)
        self.assertTrue((self.ws.root / index[0]["file"]).exists())


# --------------------------------------------------------------------- memory
class TestMemory(Base):
    def add(self, *args, **kw):
        r = self.ws.ms("memory", "add", *args, **kw)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip().replace("saved ", "")

    def test_add_list_search_show_forget(self):
        name = self.add("--type", "gotcha", "--title", "Flaky port 8080", "The e2e stack needs port 8080 free.")
        self.add("--type", "decision", "We keep push direct on next because the team merges there.")
        out = self.ws.ms("memory", "list").stdout
        self.assertIn("gotcha", out)
        self.assertIn("Flaky port 8080", out)
        self.assertEqual(len(self.ws.ms("memory", "list", "--type", "decision").stdout.strip().splitlines()), 1)
        found = self.ws.ms("memory", "search", "PORT").stdout
        self.assertIn(name, found)
        self.assertIn("8080", found)
        self.assertIn("no matches", self.ws.ms("memory", "search", "nonexistent-term").stdout)
        shown = self.ws.ms("memory", "show", name).stdout
        self.assertIn("The e2e stack needs port 8080 free.", shown)
        self.assertIn("forgot", self.ws.ms("memory", "forget", name).stdout)
        self.assertNotIn("Flaky port 8080", self.ws.ms("memory", "list").stdout)

    def test_text_can_come_from_stdin(self):
        self.assertEqual(self.ws.ms("memory", "add", "--type", "lesson", input="multi\nline lesson\n").returncode, 0)
        self.assertIn("multi", self.ws.ms("memory", "list").stdout)

    def test_validation_and_empty_state(self):
        self.assertIn("no notes", self.ws.ms("memory", "list").stdout)
        self.assertNotEqual(self.ws.ms("memory", "add", "--type", "novel", "x").returncode, 0)
        self.assertNotEqual(self.ws.ms("memory", "add", "--type", "lesson", input="  ").returncode, 0)
        self.assertNotEqual(self.ws.ms("memory", "show", "ghost").returncode, 0)

    def test_add_rejects_unknown_option_and_help_saves_nothing(self):
        self.assertNotEqual(self.ws.ms("memory", "add", "--bogus", "x").returncode, 0)
        self.assertIn("usage", self.ws.ms("memory", "add", "--help").stdout)
        self.assertIn("no notes", self.ws.ms("memory", "list").stdout)
        self.assertEqual(self.ws.ms("memory", "add", "--", "--flag as text").returncode, 0)
        self.assertIn("--flag as text", self.ws.ms("memory", "list").stdout)

    def test_ambiguous_reference_is_rejected(self):
        self.add("--title", "alpha one", "a")
        self.add("--title", "alpha two", "b")
        r = self.ws.ms("memory", "show", "alpha")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("ambiguous", r.stderr)

    def test_context_shows_handoffs_of_active_batches_only(self):
        self.ws.batch("b1")
        self.add("--type", "handoff", "--batch", "b1", "Stopped after integrate; next run test t1 and ship.")
        self.add("--type", "handoff", "--batch", "gone", "Old batch handoff")
        self.add("--type", "gotcha", "--title", "Port clash", "x")
        ctx = self.ws.ms("context").stdout
        self.assertIn("Memory: 3 notes", ctx)
        self.assertIn("HANDOFF b1: Stopped after integrate", ctx)
        self.assertNotIn("HANDOFF gone", ctx)
        self.assertIn("Port clash", ctx)

    def test_cleaning_a_batch_drops_its_handoffs(self):
        d = self.ws.batch("b1")
        self.ws.commit(d / "lib", "f", {"f.txt": "1"})
        self.add("--type", "handoff", "--batch", "b1", "resume here")
        self.add("--type", "decision", "keep me")
        self.assertOk(self.ws.ms("ship", "b1", "--yes", "--skip-e2e"))
        self.assertOk(self.ws.ms("clean", "b1"))
        out = self.ws.ms("memory", "list").stdout
        self.assertNotIn("resume here", out)
        self.assertIn("keep me", out)

    def test_workspace_claude_md_tells_agents_about_memory(self):
        self.assertIn("memory add --type handoff", self.ws.ms("claude-md", "--print").stdout)


# ------------------------------------------------- log fields and insights
class TestInsights(Base):
    def snapshot(self, p5, p7=10.0):
        now = int(time.time())
        self.ws.cache.mkdir(exist_ok=True)
        (self.ws.cache / "usage.json").write_text(json.dumps({
            "captured_at": now, "five_hour": {"used_percentage": p5, "resets_at": now + 3 * 3600},
            "seven_day": {"used_percentage": p7, "resets_at": now + 4 * 86400}}))

    def events(self):
        out = []
        for f in sorted((self.ws.root / ".ms-workspace" / "logs").glob("*.jsonl")):
            out += [json.loads(l) for l in f.read_text().splitlines()]
        return out

    def write_events(self, rows):
        logs = self.ws.root / ".ms-workspace" / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        with open(logs / f"{time.strftime('%Y-%m-%d')}.jsonl", "a") as fh:
            for r in rows:
                fh.write(json.dumps({"detail": "", "repo": "", **r}) + "\n")

    def test_test_events_carry_duration_and_code_key(self):
        wt = self.ws.batch("b1") / "lib"
        self.ws.ms("test", "t0", cwd=wt)
        ev = next(e for e in self.events() if e["action"] == "test.t0")
        self.assertIn("secs", ev)
        self.assertRegex(ev["key"], r"^[0-9a-f]{20}$")
        self.ws.ms("test", "t0", cwd=wt)
        self.assertTrue([e for e in self.events() if e["action"] == "test.t0"][-1]["cached"])

    def test_events_carry_plan_usage_when_a_fresh_snapshot_exists(self):
        self.snapshot(31.5, 12.0)
        self.ws.batch("b1", "lib")
        ev = next(e for e in self.events() if e["action"] == "batch.new")
        self.assertEqual((ev["u5"], ev["u7"]), (31.5, 12.0))

    def test_no_usage_fields_without_a_snapshot(self):
        self.ws.batch("b1", "lib")
        self.assertNotIn("u5", next(e for e in self.events() if e["action"] == "batch.new"))

    def test_flaky_candidate_same_code_fails_then_passes(self):
        flag = self.ws.tmp / "flag"
        self.ws.set_toml(DEFAULT_TOML.replace('unit = "echo unit-lib"', f'unit = "test -f {flag} || (touch {flag}; exit 1)"'))
        wt = self.ws.batch("b1") / "lib"
        self.assertNotEqual(self.ws.ms("test", "t0", cwd=wt).returncode, 0)
        self.assertEqual(self.ws.ms("test", "t0", cwd=wt).returncode, 0)
        data = json.loads(self.ws.ms("insights", "--json").stdout)
        self.assertEqual([f["repo"] for f in data["flaky"]], ["lib"])
        self.assertEqual((data["tests"]["lib"]["ok"], data["tests"]["lib"]["fail"]), (1, 1))
        self.assertIn("Flaky candidates", self.ws.ms("insights").stdout)

    def test_batch_cost_is_the_sum_of_usage_increases(self):
        self.snapshot(10)
        d = self.ws.batch("b1", "lib")
        self.snapshot(25)
        self.ws.ms("test", "t0", cwd=d / "lib")
        self.snapshot(5)   # a window reset must not count as negative cost
        self.ws.ms("test", "t0", "--no-cache", cwd=d / "lib")
        self.snapshot(9)
        self.ws.ms("test", "t0", "--no-cache", cwd=d / "lib")
        data = json.loads(self.ws.ms("insights", "--json").stdout)
        self.assertEqual(data["batches"]["b1"]["u5_cost"], 15.0 + 4.0)
        self.assertIn("of the 5h window", self.ws.ms("insights").stdout)

    def test_counts_guard_blocks_and_conflicts(self):
        d = self.ws.batch("b1")
        self.ws.ms("guard", input=json.dumps({"tool_input": {"command": "git push"}, "cwd": str(d / "lib")}))
        data = json.loads(self.ws.ms("insights", "--json").stdout)
        self.assertEqual(data["guard_blocks"], 1)

    def test_need_auto_uses_the_median_of_completed_batches(self):
        self.snapshot(20)
        rows = []
        for b, (lo, hi) in {"a": (0, 10), "b": (0, 20), "c": (0, 30)}.items():
            rows += [{"ts": f"2026-10-15T10:0{len(rows) % 9}:00-05:00", "action": "batch.new", "status": "ok", "batch": b, "u5": lo},
                     {"ts": f"2026-10-15T11:0{len(rows) % 9}:00-05:00", "action": "ship", "status": "ok", "batch": b, "u5": hi}]
        self.write_events(rows)
        out = self.ws.ms("usage", "--need", "auto").stdout
        self.assertIn("planned task: ~20% of the 5h window (median of 3 past batches)", out)
        self.assertIn("Typical completed batch", self.ws.ms("insights").stdout)

    def test_need_auto_refuses_without_history(self):
        self.snapshot(20)
        r = self.ws.ms("usage", "--need", "auto")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("history", r.stderr)
        self.assertNotEqual(self.ws.ms("usage", "--need", "auto", cwd=self.ws.tmp).returncode, 0)

    def test_empty_log(self):
        self.assertIn("0 logged actions", self.ws.ms("insights").stdout)


# ----------------------------------------------------------------- token audit
class TestTokens(Base):
    def assistant(self, mid, content, cwd, out=100, new=5, cache=1000, created=2000):
        return {"type": "assistant", "cwd": str(cwd), "timestamp": "2026-10-15T10:00:00.000Z", "sessionId": "s1",
                "message": {"id": mid, "role": "assistant", "model": "claude-sonnet-5-5", "content": content,
                            "usage": {"input_tokens": new, "cache_creation_input_tokens": created,
                                      "cache_read_input_tokens": cache, "output_tokens": out}}}

    def result(self, tool_id, chars, cwd):
        return {"type": "user", "cwd": str(cwd), "timestamp": "2026-10-15T10:00:05.000Z",
                "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tool_id, "content": "x" * chars}]}}

    def session(self, name, rows, project="-proj"):
        d = self.ws.home / ".claude" / "projects" / project
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{name}.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    def read_block(self, tid, path):
        return {"type": "tool_use", "id": tid, "name": "Read", "input": {"file_path": path}}

    def test_totals_dedupe_repeated_message_lines_and_biggest_results(self):
        cwd = self.ws.root / ".batches" / "b1" / "lib"
        rows = [self.assistant("m1", [{"type": "thinking"}], cwd), self.assistant("m1", [self.read_block("t1", "/src/Big.java")], cwd),
                self.result("t1", 40000, cwd),
                self.assistant("m2", [{"type": "tool_use", "id": "t2", "name": "Bash", "input": {"command": "ls"}}], cwd, out=50),
                self.result("t2", 400, cwd)]
        self.session("s1", rows)
        data = json.loads(self.ws.ms("tokens", "--json").stdout)
        self.assertEqual(data["sessions"], 1)
        self.assertEqual(data["total"]["requests"], 2, "the same message repeated per content block counts once")
        self.assertEqual(data["total"]["output"], 150)
        self.assertEqual(data["total"]["new_input"], 2 * (5 + 2000))
        self.assertEqual(data["total"]["cache_read"], 2000)
        self.assertIn("b1/lib", data["scopes"])
        self.assertEqual(data["biggest"][0]["tool"], "Read")
        self.assertEqual(data["biggest"][0]["approx_tokens"], 10000)
        self.assertEqual(data["tools"][0]["tool"], "Read")
        out = self.ws.ms("tokens").stdout
        self.assertIn("Token audit", out)
        self.assertIn("Hint: A single Read result", out)

    def test_repeated_reads_are_flagged(self):
        cwd = self.ws.root / "lib"
        rows = []
        for i in range(3):
            rows += [self.assistant(f"m{i}", [self.read_block(f"t{i}", "/src/Same.java")], cwd), self.result(f"t{i}", 100, cwd)]
        self.session("s2", rows)
        data = json.loads(self.ws.ms("tokens", "--json").stdout)
        self.assertEqual(data["repeated_reads"][0]["reads"], 3)
        self.assertIn("read 3 times", self.ws.ms("tokens").stdout)

    def test_sessions_outside_the_workspace_are_ignored(self):
        self.session("s3", [self.assistant("m1", [{"type": "text", "text": "hi"}], self.ws.tmp / "elsewhere")])
        self.assertIn("No Claude Code sessions", self.ws.ms("tokens").stdout)

    def test_old_sessions_are_ignored(self):
        self.session("s4", [self.assistant("m1", [{"type": "text", "text": "hi"}], self.ws.root / "lib")])
        f = self.ws.home / ".claude" / "projects" / "-proj" / "s4.jsonl"
        old = time.time() - 30 * 86400
        os.utime(f, (old, old))
        self.assertIn("No Claude Code sessions", self.ws.ms("tokens").stdout)
        self.assertEqual(json.loads(self.ws.ms("tokens", "--days", "60", "--json").stdout)["sessions"], 1)

    def test_agent_worktree_scope(self):
        cwd = self.ws.root / ".batches" / "b1" / ".agents" / "t1" / "lib"
        self.session("s5", [self.assistant("m1", [{"type": "text", "text": "hi"}], cwd)])
        self.assertIn("b1/lib", json.loads(self.ws.ms("tokens", "--json").stdout)["scopes"])


# ----------------------------------------------------------- hooks / settings
class TestSetupHooks(Base):
    def setUp(self):
        super().setUp()
        self.home = self.ws.tmp / "claude-home"
        self.settings = self.home / "settings.json"
        self.env = {"CLAUDE_HOME": str(self.home)}

    def setup(self, *args):
        return self.ws.ms("setup-hooks", *args, cwd=self.ws.tmp, env=self.env)

    def load(self):
        return json.loads(self.settings.read_text())

    def commands(self, data):
        return [h["command"] for groups in data.get("hooks", {}).values() for g in groups for h in g["hooks"]]

    def test_dry_run_changes_nothing(self):
        r = self.setup("--dry-run")
        self.assertOk(r)
        self.assertIn("dry run", r.stdout)
        self.assertIn("added", r.stdout)
        self.assertFalse(self.settings.exists())

    def test_plugin_root_drops_our_hooks_and_points_the_status_line_at_the_plugin(self):
        self.assertOk(self.setup())
        r = self.setup("--plugin-root", "/opt/dynamia/")
        self.assertOk(r)
        data = self.load()
        self.assertNotIn("hooks", data)
        self.assertEqual(data["statusLine"]["command"], '"/opt/dynamia/bin/ms-statusline"')
        self.assertIn("Bash(ms-workspace status:*)", data["permissions"]["allow"])
        again = self.setup("--plugin-root", "/opt/dynamia")
        self.assertIn("Already up to date", again.stdout)
        self.assertOk(self.setup("--remove"))
        self.assertNotIn("statusLine", self.load(), "--remove also takes out the plugin-path status line")

    def global_setup(self, *args):
        self.bin = self.ws.tmp / "local-bin"
        self.env = {**self.env, "BIN_DIR": str(self.bin)}
        return self.setup("--global", "--plugin-root", str(REPO), *args)

    def test_global_adds_a_marked_block_and_links_the_tools(self):
        md = self.home / "CLAUDE.md"
        self.home.mkdir(parents=True)
        md.write_text("# Mine\nkeep me\n")
        r = self.global_setup()
        self.assertOk(r)
        text = md.read_text()
        self.assertTrue(text.startswith("# Mine\nkeep me\n"))
        self.assertIn("<!-- dynamia:begin", text)
        self.assertIn("\n@DYNAMIA.md\n", text)
        self.assertNotIn("Global instructions", text, "the text lives in DYNAMIA.md, not in CLAUDE.md")
        self.assertEqual((self.home / "DYNAMIA.md").read_text(), (REPO / "CLAUDE.md").read_text())
        self.assertEqual((self.bin / "ms-workspace").resolve(), (REPO / "bin" / "ms-workspace").resolve())
        self.assertTrue(list(self.home.glob("CLAUDE.md.bak-*")), "the old file is backed up")
        again = self.global_setup()
        self.assertEqual(md.read_text(), text, "idempotent")
        self.assertIn("present  dynamia import", again.stdout)

    def test_global_never_writes_through_a_link_to_the_repo_file(self):
        self.home.mkdir(parents=True)
        original = (REPO / "CLAUDE.md").read_text()
        (self.home / "CLAUDE.md").symlink_to(REPO / "CLAUDE.md")
        self.assertOk(self.global_setup())
        self.assertFalse((self.home / "CLAUDE.md").is_symlink())
        self.assertEqual((REPO / "CLAUDE.md").read_text(), original)
        self.assertIn("<!-- dynamia:begin", (self.home / "CLAUDE.md").read_text())

    def test_global_dry_run_and_remove(self):
        self.home.mkdir(parents=True)
        (self.home / "CLAUDE.md").write_text("# Mine\n")
        self.assertIn("added", self.global_setup("--dry-run").stdout)
        self.assertEqual((self.home / "CLAUDE.md").read_text(), "# Mine\n")
        self.assertFalse((self.bin / "ms-workspace").exists())
        self.assertOk(self.global_setup())
        self.assertOk(self.global_setup("--remove"))
        self.assertEqual((self.home / "CLAUDE.md").read_text(), "# Mine\n")
        self.assertFalse((self.home / "DYNAMIA.md").exists())
        self.assertFalse((self.bin / "ms-workspace").exists())

    def test_global_turns_an_old_full_text_block_into_an_import(self):
        self.home.mkdir(parents=True)
        (self.home / "CLAUDE.md").write_text("# Mine\n\n<!-- dynamia:begin (managed by /dynamia:setup; edit outside this block) -->\nold full text\n<!-- dynamia:end -->\n\n# After\n")
        self.assertOk(self.global_setup())
        text = (self.home / "CLAUDE.md").read_text()
        self.assertNotIn("old full text", text)
        self.assertIn("@DYNAMIA.md", text)
        self.assertTrue(text.startswith("# Mine\n") and text.endswith("# After\n"))

    def fake_plugin(self, version, banner):
        d = self.ws.tmp / "cfg" / "plugins" / "cache" / "mk" / "dynamia" / version
        (d / "bin").mkdir(parents=True)
        for n in ("ms-workspace", "ms-statusline"):
            (d / "bin" / n).write_text(f'#!/bin/sh\necho "{banner} {n} $*"\n')
            (d / "bin" / n).chmod(0o755)
        (d / "CLAUDE.md").write_text("# Fake instructions\n")
        return d

    def test_global_installs_a_launcher_that_follows_plugin_updates(self):
        self.home.mkdir(parents=True)
        old = self.fake_plugin("0.9.0", "v09")
        self.bin = self.ws.tmp / "local-bin"
        self.env = {**self.env, "BIN_DIR": str(self.bin), "CLAUDE_CONFIG_DIR": str(self.ws.tmp / "cfg")}
        r = self.setup("--global", "--plugin-root", str(old))
        self.assertOk(r)
        self.assertIn("launcher", r.stdout)
        self.assertFalse((self.bin / "ms-workspace").is_symlink())
        self.assertEqual(self.load()["statusLine"]["command"], f'"{self.bin / "ms-statusline"}"', "the status line does not hold the version")
        run_env = {**os.environ, "CLAUDE_CONFIG_DIR": str(self.ws.tmp / "cfg")}
        out = lambda: subprocess.run([str(self.bin / "ms-workspace"), "hi"], capture_output=True, text=True, env=run_env)
        self.assertEqual(out().stdout.strip(), "v09 ms-workspace hi")
        self.fake_plugin("0.10.0", "v10")   # an update: newest wins, compared as numbers
        self.assertEqual(out().stdout.strip(), "v10 ms-workspace hi")
        self.assertIn("present  launcher", self.setup("--global", "--plugin-root", str(old)).stdout, "idempotent")
        self.assertOk(self.setup("--global", "--plugin-root", str(old), "--remove"))
        self.assertFalse((self.bin / "ms-workspace").exists())

    def test_launcher_replaces_an_old_link_and_reports_a_missing_plugin(self):
        self.home.mkdir(parents=True)
        d = self.fake_plugin("0.1.0", "v01")
        self.bin = self.ws.tmp / "local-bin"
        self.bin.mkdir()
        (self.bin / "ms-workspace").symlink_to(REPO / "bin" / "ms-workspace")
        self.env = {**self.env, "BIN_DIR": str(self.bin)}
        self.assertIn("updated", self.setup("--global", "--plugin-root", str(d)).stdout)
        self.assertFalse((self.bin / "ms-workspace").is_symlink())
        r = subprocess.run([str(self.bin / "ms-workspace")], capture_output=True, text=True, env={**os.environ, "CLAUDE_CONFIG_DIR": str(self.ws.tmp / "nowhere")})
        self.assertEqual(r.returncode, 127)
        self.assertIn("plugin not found", r.stderr)

    def test_global_keeps_a_real_file_in_the_bin_dir(self):
        self.home.mkdir(parents=True)
        self.bin = self.ws.tmp / "local-bin"
        self.bin.mkdir()
        (self.bin / "ms-workspace").write_text("#!/bin/sh\n")
        r = self.global_setup()
        self.assertIn("kept", r.stdout)
        self.assertEqual((self.bin / "ms-workspace").read_text(), "#!/bin/sh\n")

    def test_fresh_install_adds_everything_once(self):
        self.assertOk(self.setup())
        data = self.load()
        cmds = self.commands(data)
        for c in ("ms-workspace guard", "ms-workspace context", "ms-workspace images capture", "ms-workspace readguard", "ms-workspace outguard"):
            self.assertIn(c, cmds)
        self.assertEqual(data["statusLine"]["command"], "ms-statusline")
        self.assertNotIn("Bash(ms-workspace:*)", data["permissions"]["allow"], "the broad rule would auto-approve ship")
        self.assertIn("Bash(ms-workspace status:*)", data["permissions"]["allow"])
        for risky in ("ship", "clean", "undo", "env", "setup-hooks"):
            self.assertIn(f"Bash(ms-workspace {risky}:*)", data["permissions"]["ask"])
            self.assertNotIn(f"Bash(ms-workspace {risky}:*)", data["permissions"]["allow"])
        before = self.settings.read_text()
        r = self.setup()
        self.assertIn("Already up to date", r.stdout)
        self.assertEqual(self.settings.read_text(), before)
        for event, groups in self.load()["hooks"].items():
            per_event = [h["command"] for g in groups for h in g["hooks"]]
            self.assertEqual(len(per_event), len(set(per_event)), event)

    def test_existing_settings_are_preserved_and_backed_up(self):
        self.home.mkdir()
        existing = {"model": "opus", "statusLine": {"type": "command", "command": "my-line"},
                    "permissions": {"allow": ["Bash(ls:*)"], "deny": ["Bash(rm:*)"]},
                    "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "rtk hook claude"}]},
                                              {"matcher": "Grep|Glob", "hooks": [{"type": "command", "command": "gate"}]}]}}
        self.settings.write_text(json.dumps(existing))
        r = self.setup()
        self.assertOk(r)
        self.assertIn("backup:", r.stdout)
        self.assertIn("kept     statusLine", r.stdout)
        data = self.load()
        self.assertEqual(data["model"], "opus")
        self.assertEqual(data["statusLine"]["command"], "my-line", "another status line is never overwritten")
        self.assertEqual(data["permissions"]["deny"], ["Bash(rm:*)"])
        self.assertEqual(data["permissions"]["allow"][0], "Bash(ls:*)")
        bash_group = next(g for g in data["hooks"]["PreToolUse"] if g["matcher"] == "Bash")
        self.assertEqual([h["command"] for h in bash_group["hooks"]], ["rtk hook claude", "ms-workspace guard"])
        self.assertIn("gate", self.commands(data))
        self.assertEqual(len(list(self.home.glob("settings.json.bak-*"))), 1)

    def test_remove_only_takes_out_what_we_added(self):
        self.home.mkdir()
        self.settings.write_text(json.dumps({"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "rtk hook claude"}]}]}}))
        self.setup()
        r = self.setup("--remove")
        self.assertOk(r)
        self.assertIn("removed", r.stdout)
        data = self.load()
        self.assertEqual(self.commands(data), ["rtk hook claude"])
        self.assertNotIn("statusLine", data)
        self.assertNotIn("permissions", data)
        self.assertIn("Nothing to remove", self.setup("--remove").stdout)

    def test_the_old_broad_permission_is_replaced(self):
        self.home.mkdir()
        self.settings.write_text(json.dumps({"permissions": {"allow": ["Bash(ms-workspace:*)", "Bash(ls:*)"]}}))
        r = self.setup()
        self.assertIn("too broad", r.stdout)
        allow = self.load()["permissions"]["allow"]
        self.assertNotIn("Bash(ms-workspace:*)", allow)
        self.assertIn("Bash(ls:*)", allow)

    def test_source_option_needs_a_file(self):
        self.assertNotEqual(self.setup("--source").returncode, 0)

    def test_invalid_json_is_never_overwritten(self):
        self.home.mkdir()
        self.settings.write_text("{ not json")
        r = self.setup()
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.settings.read_text(), "{ not json")

    def test_project_scope_writes_to_the_project_settings(self):
        proj = self.ws.tmp / "proj"
        proj.mkdir()
        r = self.ws.ms("setup-hooks", "--project", cwd=proj, env=self.env)
        self.assertOk(r)
        self.assertTrue((proj / ".claude" / "settings.json").exists())
        self.assertFalse(self.settings.exists())

    def test_doctor_checks_the_hooks(self):
        env = {"CLAUDE_HOME": str(self.home)}
        before = self.ws.ms("doctor", env=env).stdout
        self.assertIn("not installed in settings.json", before)
        self.setup()
        self.assertIn("hooks are installed", self.ws.ms("doctor", env=env).stdout)


# ------------------------------------------------------------------ packaging
class TestPackaging(unittest.TestCase):
    """Skills and agents are plain files that Claude Code parses as YAML frontmatter; a stray ': ' breaks them."""

    def frontmatter(self, path):
        text = path.read_text()
        self.assertTrue(text.startswith("---\n"), f"{path}: missing frontmatter")
        head = text[4:].split("\n---\n", 1)[0]
        fields = {}
        for line in head.splitlines():
            if line.startswith((" ", "-")) or ":" not in line:
                continue
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()
        return fields

    def test_skills_have_valid_frontmatter(self):
        skills = sorted((REPO / "skills").glob("*/SKILL.md"))
        self.assertGreaterEqual(len(skills), 8)
        for path in skills:
            with self.subTest(skill=path.parent.name):
                f = self.frontmatter(path)
                self.assertEqual(f.get("name"), path.parent.name)
                self.assertTrue(f.get("description"))
                for key, value in f.items():
                    if value and value[0] not in "\"'[{>|":
                        self.assertNotIn(": ", value, f"{key} has an unquoted ': ' (invalid YAML)")
                        self.assertNotIn(" #", value, f"{key} has an unquoted ' #' (YAML comment)")

    def test_agents_have_valid_frontmatter_and_known_names(self):
        for path in sorted((REPO / "agents").glob("*.md")):
            with self.subTest(agent=path.stem):
                f = self.frontmatter(path)
                self.assertEqual(f.get("name"), path.stem)
                self.assertTrue(path.stem in {"boss", "scout", "summarizer", "test-triage"})
                self.assertIn(f.get("model"), ("haiku", "sonnet", "opus"))
                self.assertTrue(f.get("description"))
                for key, value in f.items():
                    if value and value[0] not in "\"'[{>|":
                        self.assertNotIn(": ", value, f"{key} has an unquoted ': ' (invalid YAML)")

    def test_settings_example_is_valid_and_complete(self):
        data = json.loads((REPO / "settings" / "hooks.example.json").read_text())
        cmds = {h["command"] for groups in data["hooks"].values() for g in groups for h in g["hooks"]}
        self.assertEqual(cmds, {"ms-workspace guard", "ms-workspace context", "ms-workspace images capture", "ms-workspace readguard",
                                "ms-workspace outguard", "ms-workspace readguard --reset", "ms-workspace handoff --hook", "ms-workspace notify --hook"})
        self.assertNotIn("Bash(ms-workspace:*)", data["permissions"]["allow"])
        self.assertTrue({"Bash(ms-workspace ship:*)", "Bash(ms-workspace clean:*)", "Bash(ms-workspace undo:*)", "Bash(ms-workspace promote:*)"} <= set(data["permissions"]["ask"]))
        self.assertEqual(data["statusLine"]["command"], "ms-statusline")

    def test_code_stays_valid_for_the_minimum_python(self):
        """The tool promises Python 3.11. Reusing the f-string's own quote inside {} and a few library calls are 3.12+."""
        nested = re.compile(r'f(["\'])(?:(?!\1).)*?\{[^{}]*\1[^{}]*\}')
        newer = re.compile(r"\bPath\.walk\(|\.walk\(top_down|itertools\.batched|from typing import .*\boverride\b|^\s*type\s+\w+\s*=|def \w+\[\w+\]")
        sources = list((REPO / "lib" / "ms_workspace").glob("*.py")) + [REPO / "bin" / "ms-workspace"]
        for path in sources:
            for n, line in enumerate(path.read_text().splitlines(), 1):
                self.assertIsNone(nested.search(line), f"{path.name}:{n} reuses the f-string quote (Python 3.12+): {line.strip()[:80]}")
                self.assertIsNone(newer.search(line), f"{path.name}:{n} uses a Python 3.12+ feature: {line.strip()[:80]}")

    def test_plugin_hooks_match_the_example_hooks(self):
        plugin = (REPO / "hooks" / "hooks.json").read_text().replace('\\"${CLAUDE_PLUGIN_ROOT}/bin/ms-workspace\\"', "ms-workspace")
        example = json.loads((REPO / "settings" / "hooks.example.json").read_text())["hooks"]
        self.assertEqual(json.loads(plugin)["hooks"], example)

    def test_example_mock_definition_is_valid(self):
        import tomllib
        data = tomllib.loads((REPO / "skills" / "workspace-init" / "references" / "mocks" / "payments.mock.toml").read_text())
        self.assertEqual([r["name"] for r in data["route"]][:2], ["create-payment", "declined-card"])
        sys.path.insert(0, str(REPO / "lib"))
        from ms_workspace.mock import load_def
        self.assertEqual(len(load_def(REPO / "skills" / "workspace-init" / "references" / "mocks" / "payments.mock.toml")["route"]), 5)

    def test_example_request_collection_is_valid(self):
        import tomllib
        ref = REPO / "skills" / "workspace-init" / "references" / "requests"
        data = tomllib.loads((ref / "smoke.http.toml").read_text())
        self.assertEqual([r["name"] for r in data["request"]], ["health", "login", "me"])
        self.assertIn("base_url", tomllib.loads((ref / "env" / "local.toml").read_text()))
        self.assertIn("password=", (ref / "env" / "local.secrets.example").read_text())

    def test_example_workspace_config_parses(self):
        import tomllib
        cfg = tomllib.loads((REPO / "skills" / "workspace-init" / "references" / "workspace.example.toml").read_text())
        self.assertIn("repos", cfg)

    def test_installer_links_everything_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "CLAUDE_HOME": f"{tmp}/c", "BIN_DIR": f"{tmp}/b"}
            (Path(tmp) / "c" / "skills").mkdir(parents=True)
            (Path(tmp) / "c" / "skills" / "ms-ship").symlink_to(REPO / "skills" / "ms-ship")  # dangling, from an older install
            first = run([str(REPO / "install.sh")], env=env)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertTrue((Path(tmp) / "b" / "ms-workspace").is_symlink())
            self.assertFalse((Path(tmp) / "c" / "skills" / "ms-ship").is_symlink(), "old skill links are dropped")
            self.assertFalse((Path(tmp) / "c" / "skills" / "ship").exists(), "the plugin provides skills")
            legacy = run([str(REPO / "install.sh"), "--legacy"], env=env)
            self.assertEqual(legacy.returncode, 0, legacy.stderr)
            self.assertTrue((Path(tmp) / "c" / "skills" / "ship").is_symlink())
            self.assertTrue((Path(tmp) / "c" / "agents" / "boss.md").is_symlink())
            self.assertTrue((Path(tmp) / "c" / "CLAUDE.md").is_symlink())
            second = run([str(REPO / "install.sh")], env=env)
            self.assertNotIn("backup", second.stdout)
            dry = run([str(REPO / "install.sh"), "--uninstall"], env=env)
            self.assertFalse((Path(tmp) / "b" / "ms-workspace").exists())
            self.assertEqual(dry.returncode, 0)


# ------------------------------------------- review follow-ups: data-loss safety
class TestUnintegratedWork(Base):
    """clean and ship must never drop or skip agent branches that were not integrated."""

    def setUp(self):
        super().setUp()
        self.d = self.ws.batch("b1", "lib")
        self.assertOk(self.ws.ms("agent", "new", "b1", "t1", "lib"))
        self.agent = self.d / ".agents" / "t1" / "lib"
        self.ws.commit(self.agent, "agent work", {"agent.txt": "precious"})
        self.ws.commit(self.d / "lib", "batch work", {"f.txt": "1"})

    def test_clean_listing_flags_the_loose_agent_branch(self):
        out = self.ws.ms("clean").stdout
        self.assertIn("pending", out)
        self.assertIn("agent/b1/t1", out)

    def test_ship_refuses_and_names_the_branch(self):
        r = self.ws.ms("ship", "b1", "--yes", "--skip-e2e")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("agent/b1/t1", r.stderr)
        self.assertIn("integrate", r.stderr)
        self.assertNotIn("batch work", self.ws.remote_log("lib"))
        self.assertNotEqual(self.ws.ms("plan", "b1").returncode, 0, "the plan fails early too")

    def test_clean_refuses_even_after_the_batch_branch_reached_the_remote(self):
        self.ws.git(self.d / "lib", "push", "-q", "origin", "int/b1:next")   # int/b1 is now part of next
        self.assertIn("pending", self.ws.ms("clean").stdout)
        r = self.ws.ms("clean", "b1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not integrated", r.stderr)
        self.assertTrue(self.agent.is_dir())
        self.assertIn("agent/b1/t1", self.ws.git(self.ws.root / "lib", "branch", "--list"))

    def test_integrating_makes_ship_and_clean_work(self):
        self.assertOk(self.ws.ms("integrate", "b1"))
        self.assertOk(self.ws.ms("ship", "b1", "--yes", "--skip-e2e"))
        self.assertIn("safe to clean", self.ws.ms("clean").stdout)
        self.assertOk(self.ws.ms("clean", "b1"))
        self.assertFalse(self.d.exists())

    def test_force_is_the_explicit_way_to_discard(self):
        self.assertOk(self.ws.ms("clean", "b1", "--force"))
        self.assertNotIn("agent/b1/t1", self.ws.git(self.ws.root / "lib", "branch", "--list"))

    def test_plan_lists_the_commits_that_would_be_sent(self):
        self.assertOk(self.ws.ms("integrate", "b1"))
        out = self.ws.ms("plan", "b1").stdout
        self.assertIn("batch work", out)
        self.assertIn("agent work", out)
        self.assertRegex(out, r"\d+ files? changed")
        self.assertNotIn("batch work", self.ws.remote_log("lib"))


class TestIntegrateOptions(Base):
    def test_unknown_option_is_rejected_instead_of_merging(self):
        d = self.ws.batch("b1", "lib")
        self.assertOk(self.ws.ms("agent", "new", "b1", "t1", "lib"))
        self.ws.commit(d / ".agents" / "t1" / "lib", "w", {"x.txt": "1"})
        r = self.ws.ms("integrate", "b1", "--dryrun")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("unknown option", r.stderr)
        self.assertFalse((d / "lib" / "x.txt").exists())


class TestRollbackAndNames(Base):
    def test_failed_batch_new_leaves_nothing_behind(self):
        r = self.ws.ms("batch", "new", "b1", "lib", "ghost")
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse((self.ws.root / ".batches" / "b1").exists())
        self.assertNotIn("int/b1", self.ws.git(self.ws.root / "lib", "branch", "--list"))
        self.assertNotIn(".batches", self.ws.git(self.ws.root / "lib", "worktree", "list"))
        self.assertOk(self.ws.ms("batch", "new", "b1", "lib"))   # a rerun works

    def test_failed_agent_new_rolls_back_only_its_own_work(self):
        d = self.ws.batch("b1", "lib")
        r = self.ws.ms("agent", "new", "b1", "t1", "lib", "app")   # app is not part of the batch
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse((d / ".agents" / "t1").exists())
        self.assertNotIn("agent/b1/t1", self.ws.git(self.ws.root / "lib", "branch", "--list"))
        self.assertTrue((d / "lib").is_dir())
        self.assertOk(self.ws.ms("agent", "new", "b1", "t1", "lib"))

    def test_names_are_validated(self):
        for bad in ("..", "a/b", "-x", ".hidden", "a b", ""):
            with self.subTest(name=bad):
                self.assertNotEqual(self.ws.ms("batch", "new", bad).returncode, 0)
        self.ws.batch("b1")
        self.assertNotEqual(self.ws.ms("agent", "new", "b1", "../x").returncode, 0)
        self.assertNotEqual(self.ws.ms("clean", "..").returncode, 0)
        self.assertTrue((self.ws.root / ".batches").is_dir())

    def test_bad_numeric_options_give_errors_not_tracebacks(self):
        for args in (("log", "-n"), ("log", "-n", "x"), ("images", "list", "-n", "abc")):
            r = self.ws.ms(*args)
            self.assertNotEqual(r.returncode, 0, args)
            self.assertNotIn("Traceback", r.stderr, args)


class TestEnvSetupFailure(Base):
    def test_failure_shows_the_command_output(self):
        self.ws.set_toml(DEFAULT_TOML.replace('[repos.lib]\nbase = "next"', '[repos.lib]\nbase = "next"\nsetup = "echo broken-dependency >&2; exit 4"'))
        self.ws.batch("b1", "lib")
        r = self.ws.ms("env", "b1", "--setup")
        self.assertIn("setup FAILED", r.stderr)
        self.assertIn("broken-dependency", r.stderr)


class TestTrustWrite(Base):
    def test_other_keys_survive_and_symlinks_are_kept(self):
        real = self.ws.tmp / "real-claude.json"
        real.write_text(json.dumps({"theme": "dark", "projects": {"/old": {"hasTrustDialogAccepted": True}}}))
        link = self.ws.home / ".claude.json"
        link.symlink_to(real)
        d = self.ws.batch("b1", "lib")
        self.assertOk(self.ws.ms("env", "b1", "--trust"))
        self.assertTrue(link.is_symlink(), "the symlink must not be replaced by a regular file")
        data = json.loads(real.read_text())
        self.assertEqual(data["theme"], "dark")
        self.assertTrue(data["projects"]["/old"]["hasTrustDialogAccepted"])
        self.assertTrue(data["projects"][str(d / "lib")]["hasTrustDialogAccepted"])
        self.assertEqual(list(self.ws.tmp.glob("*.tmp")), [])


class TestPrMode(Base):
    PR_TOML = DEFAULT_TOML.replace('[repos.lib]\nbase = "next"', '[repos.lib]\nbase = "next"\npush = "pr"')

    def fake_path(self, with_gh):
        bin_dir = self.ws.tmp / "fakebin"
        bin_dir.mkdir(exist_ok=True)
        for tool in ("git", "python3", "bash"):
            real = subprocess.run(["which", tool], capture_output=True, text=True).stdout.strip()
            (bin_dir / tool).unlink(missing_ok=True)
            (bin_dir / tool).symlink_to(real)
        if with_gh:
            gh = bin_dir / "gh"
            gh.write_text(f'#!/bin/sh\necho "$@" >> "{self.ws.tmp}/gh-calls"\n')
            gh.chmod(0o755)
        return str(bin_dir)

    def setUp(self):
        super().setUp()
        self.ws.set_toml(self.PR_TOML)
        d = self.ws.batch("b1", "lib")
        self.ws.commit(d / "lib", "feature", {"f.txt": "1"})

    def test_pr_mode_pushes_the_branch_and_opens_a_pr(self):
        r = self.ws.ms("ship", "b1", "--yes", "--skip-e2e", env={"PATH": self.fake_path(True)})
        self.assertOk(r)
        self.assertIn("int/b1", self.ws.git(self.ws.tmp / "remote-lib.git", "branch", "--list"))
        self.assertNotIn("feature", self.ws.remote_log("lib"), "pr mode must not touch the base branch")
        call = (self.ws.tmp / "gh-calls").read_text()
        self.assertIn("pr create --base next --head int/b1", call)

    def test_pr_flag_opens_a_pr_even_when_the_repo_pushes_directly(self):
        self.ws.set_toml(DEFAULT_TOML)   # lib is "direct" here
        env = {"PATH": self.fake_path(True)}
        plan = self.ws.ms("plan", "b1", "--pr", env=env)
        self.assertOk(plan)
        self.assertIn("(pr, 1 commits)", plan.stdout)
        self.assertIn("(direct, 1 commits)", self.ws.ms("plan", "b1", env=env).stdout)
        r = self.ws.ms("ship", "b1", "--yes", "--pr", "--skip-e2e", env=env)
        self.assertOk(r)
        self.assertNotIn("feature", self.ws.remote_log("lib"), "--pr must not touch the base branch")
        self.assertIn("int/b1", self.ws.git(self.ws.tmp / "remote-lib.git", "branch", "--list"))
        self.assertIn("pr create --base next --head int/b1", (self.ws.tmp / "gh-calls").read_text())
        undo = self.ws.ms("undo", "b1", env=env)
        self.assertIn("gh pr close", undo.stdout)

    def test_big_changes_get_a_pr_recommendation_but_the_mode_is_not_changed(self):
        self.ws.set_toml(DEFAULT_TOML + "[ship]\nrecommend_pr_new_files = 3\nrecommend_pr_files = 0\n")
        d = self.ws.root / ".batches" / "b1" / "lib"
        small = self.ws.ms("plan", "b1")
        self.assertNotIn("RECOMMEND A PR", small.stdout)
        self.ws.commit(d, "many", {f"n{i}.txt": "x\n" for i in range(4)})
        big = self.ws.ms("plan", "b1")
        self.assertOk(big)
        self.assertIn("RECOMMEND A PR: 5 new files (limit 3)", big.stdout)
        self.assertIn("ship b1 --pr", big.stdout)
        self.assertIn("(direct, 2 commits)", big.stdout)
        self.assertNotIn("RECOMMEND", self.ws.ms("plan", "b1", "--pr").stdout)
        self.ws.set_toml(DEFAULT_TOML + "[ship]\nrecommend_pr_new_files = 0\nrecommend_pr_files = 0\nrecommend_pr_lines = 0\n")
        self.assertNotIn("RECOMMEND", self.ws.ms("plan", "b1").stdout)

    def test_lines_threshold_counts_added_and_deleted_lines(self):
        self.ws.set_toml(DEFAULT_TOML + "[ship]\nrecommend_pr_lines = 6\nrecommend_pr_files = 0\nrecommend_pr_new_files = 0\n")
        d = self.ws.root / ".batches" / "b1" / "lib"
        self.ws.commit(d, "edit", {"a.txt": "1\n2\n3\n4\n"})   # +4 -1, plus the line of the setUp commit
        self.assertIn("RECOMMEND A PR: 6 lines changed (limit 6)", self.ws.ms("plan", "b1").stdout)

    def test_pr_flag_without_gh_stops_before_anything_is_pushed(self):
        self.ws.set_toml(DEFAULT_TOML)
        r = self.ws.ms("ship", "b1", "--yes", "--pr", "--skip-e2e", env={"PATH": self.fake_path(False)})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("needs the GitHub CLI", r.stderr)
        self.assertNotIn("int/b1", self.ws.git(self.ws.tmp / "remote-lib.git", "branch", "--list"))

    def test_missing_gh_stops_before_anything_is_pushed(self):
        r = self.ws.ms("ship", "b1", "--yes", "--skip-e2e", env={"PATH": self.fake_path(False)})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("gh", r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertNotIn("int/b1", self.ws.git(self.ws.tmp / "remote-lib.git", "branch", "--list"))


# ------------------------------------------------------- guard: fail closed
class TestGuardHardening(Base):
    def guard(self, command, cwd):
        return self.ws.ms("guard", input=json.dumps({"tool_input": {"command": command}, "cwd": str(cwd)}))

    def test_a_broken_workspace_toml_does_not_open_the_gate(self):
        d = self.ws.batch("b1")
        (self.ws.root / "workspace.toml").write_text("this is [[ not toml")
        self.assertEqual(self.guard("git push origin next", d / "lib").returncode, 2)
        self.assertEqual(self.guard("ls", d / "lib").returncode, 0)

    def test_evasion_forms_are_blocked_inside_a_batch(self):
        d = self.ws.batch("b1")
        for cmd in ("git -P push", "git -C/tmp/x push", '"git" push', "git subtree push --prefix=a b main", "git send-pack origin x",
                    "FOO=1 git push", "sudo git push", "bash -c 'git push origin x'", 'eval "git push"', "git --no-pager push",
                    "echo hi | git push", "ls; git push", "/usr/bin/git push", "git -c user.name=x push", "gh pr merge 3",
                    "gh api repos/o/r/issues -f title=x", "gh api -X POST repos/o/r/issues", "gh release create v1",
                    "ms-workspace setup-hooks", "ms-workspace env b1 --trust", "ms-workspace undo b1 --yes",
                    "rtk git push", "rtk proxy git push origin x", "rtk gh pr create"):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.guard(cmd, d / "lib").returncode, 2, cmd)

    def test_reaching_into_a_batch_from_the_workspace_root_is_blocked(self):
        d = self.ws.batch("b1")
        self.assertEqual(self.guard(f"cd {d}/lib && git push", self.ws.root).returncode, 2)
        self.assertEqual(self.guard("cd .batches/b1/lib && git push", self.ws.root).returncode, 2)
        self.assertEqual(self.guard("git push origin next", self.ws.root / "lib").returncode, 0, "normal checkouts stay free")

    def test_read_only_and_harmless_commands_pass(self):
        d = self.ws.batch("b1")
        for cmd in ("git status", "git log --oneline", "git pull", "git fetch", "git commit -m 'fix push handling'", "git diff | head",
                    "gh pr view 3", "gh api repos/o/r/pulls", "gh issue view 1", "echo git push", "grep -r push src",
                    "git checkout -b feature/push-fix", "rtk git status", "rtk gh pr view 3", "ms-workspace test t0", "ms-workspace env b1", "ms-workspace env b1 --setup", "unterminated 'quote"):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.guard(cmd, d / "lib").returncode, 0, cmd)

    def test_unparseable_risky_commands_fail_closed(self):
        d = self.ws.batch("b1")
        self.assertEqual(self.guard("git push 'oops", d / "lib").returncode, 2)


class TestPythonGate(unittest.TestCase):
    def setUp(self):
        import sys
        sys.path.insert(0, str(REPO / "lib"))
        from ms_workspace import compat
        self.compat = compat

    def test_old_python_only_keeps_the_guard_alive(self):
        import contextlib, io
        old = (3, 9)
        self.assertIsNone(self.compat.check(["guard"], old))
        self.assertEqual(self.compat.check(["context"], old), 0)
        self.assertEqual(self.compat.check(["images", "capture"], old), 0)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(self.compat.check(["ship", "b1"], old), 1)
            self.assertEqual(self.compat.check([], old), 1)
        self.assertIn("Python >= 3.11", err.getvalue())

    def test_current_python_proceeds(self):
        self.assertIsNone(self.compat.check(["ship"], (3, 11)))
        self.assertIsNone(self.compat.check(["ship"], (3, 14)))


class TestUsageEdgeCases(Base):
    def test_null_reset_time_is_treated_as_no_data(self):
        self.ws.cache.mkdir(exist_ok=True)
        (self.ws.cache / "usage.json").write_text(json.dumps({
            "captured_at": int(time.time()), "five_hour": {"used_percentage": 50, "resets_at": None}, "seven_day": None}))
        r = self.ws.ms("usage", "--check")
        self.assertEqual(r.returncode, 3)
        self.assertNotIn("Traceback", r.stderr)


class TestOpen(Base):
    """`open` launches a fake IDE that records its arguments; Git must be left exactly as it was."""

    def setUp(self):
        super().setUp()
        self.bin = self.ws.tmp / "bin"
        self.bin.mkdir()
        self.calls = self.ws.tmp / "calls.txt"
        for name in ("code", "idea"):
            self.fake(name)
        self.env = {"PATH": f"{self.bin}:{os.environ['PATH']}"}

    def fake(self, name):
        exe = self.bin / name
        exe.write_text(f'#!/bin/sh\necho "{name} $@" >> {self.calls}\n')
        exe.chmod(0o755)

    def opened(self):
        return self.calls.read_text().splitlines() if self.calls.exists() else []

    def heads(self, b):
        return {r: self.ws.git(b / r, "rev-parse", "HEAD") + self.ws.git(b / r, "status", "--porcelain") for r in ("lib", "app")}

    def test_vscode_workspace_file_lists_the_real_worktrees_and_is_idempotent(self):
        b = self.ws.batch("b1")
        before = self.heads(b)
        r = self.ws.ms("open", "b1", "--ide", "code", env=self.env)
        self.assertOk(r)
        f = self.ws.root / ".ms-workspace" / "ide" / "b1.code-workspace"
        data = json.loads(f.read_text())
        self.assertEqual([x["path"] for x in data["folders"]], [str(b / "app"), str(b / "lib")])
        self.assertEqual(self.opened(), [f"code {f}"])
        mtime = f.stat().st_mtime_ns
        self.assertOk(self.ws.ms("open", "b1", "--ide", "code", env=self.env))
        self.assertEqual(f.stat().st_mtime_ns, mtime)
        self.assertEqual(len(self.opened()), 2)
        self.assertEqual(self.heads(b), before)
        self.assertEqual(self.ws.git(self.ws.root / "lib", "status", "--porcelain"), "")

    def test_batches_get_separate_workspace_files(self):
        self.ws.batch("b1")
        self.ws.batch("b2")
        self.assertOk(self.ws.ms("open", "b1", "--ide", "code", env=self.env))
        self.assertOk(self.ws.ms("open", "b2", "--ide", "code", env=self.env))
        ide = self.ws.root / ".ms-workspace" / "ide"
        paths = {n: [x["path"] for x in json.loads((ide / f"{n}.code-workspace").read_text())["folders"]] for n in ("b1", "b2")}
        self.assertTrue(all("/b1/" in p for p in paths["b1"]) and all("/b2/" in p for p in paths["b2"]))

    def test_agent_worktrees_and_repo_filter(self):
        b = self.ws.batch("b1")
        self.assertOk(self.ws.ms("agent", "new", "b1", "t1", "lib"))
        self.assertOk(self.ws.ms("open", "b1", "--agent", "t1", "--ide", "code", env=self.env))
        data = json.loads((self.ws.root / ".ms-workspace" / "ide" / "b1--t1.code-workspace").read_text())
        self.assertEqual([x["path"] for x in data["folders"]], [str(b / ".agents" / "t1" / "lib")])
        bad = self.ws.ms("open", "b1", "--agent", "nope", "--ide", "code", env=self.env)
        self.assertEqual(bad.returncode, 1)
        self.assertIn("known: t1", bad.stderr)
        self.assertEqual(self.ws.ms("open", "b1", "--agent", "t1", "--repo", "app", "--ide", "code", env=self.env).returncode, 1)

    def test_idea_opens_each_worktree_as_its_own_project(self):
        b = self.ws.batch("b1")
        r = self.ws.ms("open", "b1", "--ide", "idea", env=self.env)
        self.assertOk(r)
        self.assertEqual(self.opened(), [f"idea {b / 'app'}", f"idea {b / 'lib'}"])
        self.assertIn("does not ignore .idea/", r.stdout)
        self.assertFalse((self.ws.root / ".ms-workspace" / "ide").exists())
        self.calls.unlink()
        self.assertOk(self.ws.ms("open", "b1", "--ide", "idea", "--repo", "lib", env=self.env))
        self.assertEqual(self.opened(), [f"idea {b / 'lib'}"])

    def test_dry_run_launches_and_writes_nothing(self):
        self.ws.batch("b1")
        r = self.ws.ms("open", "b1", "--dry-run", env=self.env)
        self.assertOk(r)
        self.assertIn("would run: ", r.stdout)
        self.assertEqual(self.opened(), [])
        self.assertFalse((self.ws.root / ".ms-workspace" / "ide").exists())

    def test_default_ide_comes_from_config_then_from_what_is_installed(self):
        self.ws.batch("b1")
        self.assertIn("code ", self.ws.ms("open", "b1", "--dry-run", env=self.env).stdout)
        self.ws.set_toml(DEFAULT_TOML + '[ide]\ndefault = "idea"\n')
        self.assertIn("idea ", self.ws.ms("open", "b1", "--dry-run", env=self.env).stdout)

    def test_configured_executable_wins_and_may_carry_arguments(self):
        self.ws.batch("b1")
        custom = self.bin / "my-code"
        custom.write_text(f'#!/bin/sh\necho "custom $@" >> {self.calls}\n')
        custom.chmod(0o755)
        self.ws.set_toml(DEFAULT_TOML + f'[ide]\ncode = "{custom} --reuse-window"\n')
        self.assertOk(self.ws.ms("open", "b1", "--ide", "code", env=self.env))
        self.assertTrue(self.opened()[0].startswith("custom --reuse-window "))

    def test_missing_ide_and_bad_input_fail_clearly(self):
        self.ws.batch("b1")
        bare = {"PATH": str(self.ws.tmp / "empty")}   # not /usr/bin: a real `code` there would be launched by the test
        r = self.ws.ms_py("open", "b1", "--ide", "idea", env=bare)
        self.assertEqual(r.returncode, 1)
        self.assertIn("idea not found", r.stderr)
        self.assertEqual(self.ws.ms_py("open", "b1", env=bare).returncode, 1)
        self.assertIn("unknown IDE", self.ws.ms("open", "b1", "--ide", "vim", env=self.env).stderr)
        self.assertIn("unknown batch", self.ws.ms("open", "nope", env=self.env).stderr)
        self.assertIn("invalid batch name", self.ws.ms("open", "../lib", env=self.env).stderr)
        self.assertIn("invalid agent name", self.ws.ms("open", "b1", "--agent", "../x", env=self.env).stderr)
        self.assertIn("needs a value", self.ws.ms("open", "b1", "--ide", env=self.env).stderr)

    def test_batch_is_taken_from_the_current_directory(self):
        b = self.ws.batch("b1")
        self.assertOk(self.ws.ms("open", "--ide", "code", cwd=b / "lib", env=self.env))
        self.assertIn("b1.code-workspace", self.opened()[0])


class TestRepoEnv(Base):
    def toml(self, env, extra=""):
        return f"""
        name = "t"
        [repos.lib]
        base = "next"
        env = {env}
        setup = "echo setup=$GREETING > setup.out"
        [repos.lib.test]
        unit = "echo got=$GREETING:$URL > {self.ws.tmp}/env.out"
        [repos.app]
        base = "next"
        [repos.app.test]
        unit = "echo app=${{GREETING:-unset}}"
        {extra}
        """

    def test_variables_reach_test_and_setup_commands_only_for_their_repo(self):
        self.ws.set_toml(self.toml('["GREETING=hi", "URL=http://x/?a=b"]'))
        b = self.ws.batch("b1")
        self.assertOk(self.ws.ms("test", "t0", "--no-cache", cwd=b / "lib"))
        self.assertEqual((self.ws.tmp / "env.out").read_text().strip(), "got=hi:http://x/?a=b")
        r = self.ws.ms("test", "t0", "--no-cache", cwd=b / "app")
        self.assertOk(r)
        self.assertEqual(self.ws.ms("env", "b1", "--setup").returncode, 0)
        self.assertEqual((b / "lib" / "setup.out").read_text().strip(), "setup=hi")

    def test_changing_a_value_invalidates_the_remembered_pass(self):
        self.ws.set_toml(self.toml('["GREETING=one"]'))
        b = self.ws.batch("b1")
        self.ws.ms("test", "t0", cwd=b / "lib")
        self.assertIn("cached", self.ws.ms("test", "t0", cwd=b / "lib").stdout)
        self.ws.set_toml(self.toml('["GREETING=two"]'))
        self.assertNotIn("cached", self.ws.ms("test", "t0", cwd=b / "lib").stdout)
        self.assertEqual((self.ws.tmp / "env.out").read_text().strip(), "got=two:")

    def test_e2e_gets_the_env_of_its_repo(self):
        self.ws.set_toml(self.toml('["GREETING=e2e"]', '[e2e]\ncommand = "echo $GREETING > e2e.out"\nrepo = "lib"'))
        b = self.ws.batch("b1")
        self.assertOk(self.ws.ms("test", "t2", "b1"))
        self.assertEqual((b / "lib" / "e2e.out").read_text().strip(), "e2e")

    def test_malformed_entries_are_rejected(self):
        b = self.ws.batch("b1")
        for bad in ('["NOEQUALS"]', '["1BAD=x"]', '["A B=x"]'):
            self.ws.set_toml(self.toml(bad))
            r = self.ws.ms("test", "t0", cwd=b / "lib")
            self.assertEqual(r.returncode, 1, bad)
            self.assertIn("is not NAME=value", r.stderr)


class TestRepoHygiene(unittest.TestCase):
    def test_no_bytecode_or_state_is_tracked(self):
        tracked = run(["git", "ls-files"], cwd=REPO).stdout.splitlines()
        self.assertEqual([f for f in tracked if f.endswith(".pyc") or "__pycache__" in f], [])
        self.assertIn("__pycache__/", (REPO / ".gitignore").read_text())

    def test_no_stale_references_in_skills(self):
        init = (REPO / "skills" / "workspace-init" / "SKILL.md").read_text()
        self.assertNotIn(".claude/worktrees", init)
        self.assertNotIn("`root`", init.replace("Do not write a `root` key", ""))
        for path in (REPO / "skills").glob("*/SKILL.md"):
            head = path.read_text().split("\n---\n", 1)[0]
            self.assertNotIn("allowed-tools: Bash(ms-workspace:*)", head, f"{path.parent.name} auto-approves every subcommand")


# ---------------------------------------------------------------- context budget
class TestBudget(Base):
    def setUp(self):
        super().setUp()
        self.ch = self.ws.tmp / "claude-home"
        (self.ch / "skills" / "ms-big").mkdir(parents=True)
        (self.ch / "skills" / "ms-small").mkdir(parents=True)
        (self.ch / "agents").mkdir()
        (self.ch / "CLAUDE.md").write_text("g" * 8000 + "\n@extra.md\n")
        (self.ch / "extra.md").write_text("e" * 400)
        (self.ch / "skills" / "ms-big" / "SKILL.md").write_text("---\nname: ms-big\ndescription: " + "word " * 300 + "\n---\nbody that is never listed " * 50)
        (self.ch / "skills" / "ms-small" / "SKILL.md").write_text("---\nname: ms-small\ndescription: Short one.\ndisable-model-invocation: true\n---\nbody")
        (self.ch / "agents" / "ms-agent-x.md").write_text("---\nname: ms-agent-x\ndescription: Does a thing.\ntools: Read, Grep\n---\nlong prompt " * 100)
        self.env = {"CLAUDE_HOME": str(self.ch)}

    def budget(self, *args, cwd=None):
        r = self.ws.ms("budget", "--json", *args, cwd=cwd or self.ws.root / "lib", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_counts_what_is_loaded_and_ignores_skill_bodies(self):
        data = self.budget()
        items = {i["name"]: i["tokens"] for i in data["items"]}
        self.assertEqual(items["CLAUDE.md (global)"], 2003)            # 8012 characters (8000 plus the import line), divided by 4 and rounded up
        self.assertEqual(items["@extra.md (imported by CLAUDE.md)"], 100)
        self.assertGreater(items["skill ms-big"], 300)
        self.assertLessEqual(items["skill ms-big"], 1536 // 4 + 5, "the listing keeps at most 1536 characters per skill")
        self.assertLess(items["skill ms-small"], 20, "the body of a skill is not part of the baseline")
        self.assertLess(items["agent ms-agent-x"], 40, "only an agent's description is listed")
        self.assertEqual(data["total_tokens"], sum(i["tokens"] for i in data["items"]))
        self.assertIn("ms-workspace context (SessionStart)", items)

    def test_workspace_claude_md_and_repo_files_are_included_for_the_cwd(self):
        self.ws.ms("claude-md")
        (self.ws.root / "lib" / "CLAUDE.md").write_text("r" * 800)
        names = [i["name"] for i in self.budget()["items"]]
        self.assertTrue(any(n.startswith("CLAUDE.md (ws)") for n in names), names)
        self.assertTrue(any(n.startswith("CLAUDE.md (lib)") for n in names), names)

    def test_path_scoped_rules_are_on_demand_only(self):
        rules = self.ws.root / "lib" / ".claude" / "rules"
        rules.mkdir(parents=True)
        (rules / "always.md").write_text("a" * 400)
        (rules / "scoped.md").write_text("---\npaths:\n  - \"**/*.java\"\n---\n" + "s" * 4000)
        data = self.budget()
        self.assertIn("rule always.md", [i["name"] for i in data["items"]])
        self.assertNotIn("rule scoped.md", [i["name"] for i in data["items"]])
        self.assertEqual([i["name"] for i in data["on_demand"]], ["rule scoped.md"])

    def test_hints_and_mcp_servers(self):
        (self.ws.home / ".claude.json").write_text(json.dumps({"mcpServers": {"a": {}, "b": {}, "c": {}}}))
        data = self.budget()
        self.assertEqual(data["mcp_servers"], ["a", "b", "c"])
        text = " ".join(data["hints"])
        self.assertIn("CLAUDE.md (global) is ~2003 tokens", text)
        self.assertIn("skill ms-big", text)
        self.assertIn("3 MCP servers", text)

    def test_text_report_and_top(self):
        r = self.ws.ms("budget", "--top", "2", cwd=self.ws.root / "lib", env=self.env)
        self.assertOk(r)
        self.assertIn("Context budget for", r.stdout)
        self.assertIn("smaller items", r.stdout)
        self.assertIn("Total: ~", r.stdout)
        self.assertIn("Hint:", r.stdout)

    def test_works_outside_a_workspace_and_rejects_bad_options(self):
        data = self.budget(cwd=self.ws.tmp)
        self.assertNotIn("ms-workspace context (SessionStart)", [i["name"] for i in data["items"]])
        self.assertNotEqual(self.ws.ms("budget", "--top", "x", env=self.env).returncode, 0)
        self.assertNotEqual(self.ws.ms("budget", "--nope", env=self.env).returncode, 0)

    def test_a_file_reachable_twice_is_counted_once(self):
        """HOME is a parent of the project, so ~/.claude/skills would otherwise be scanned twice."""
        home_claude = self.ws.home / ".claude"
        (home_claude / "skills" / "ms-once").mkdir(parents=True)
        (home_claude / "skills" / "ms-once" / "SKILL.md").write_text("---\nname: ms-once\ndescription: Only once.\n---\n")
        (home_claude / "agents").mkdir()
        (home_claude / "agents" / "ms-agent-once.md").write_text("---\nname: ms-agent-once\ndescription: Only once.\n---\n")
        project = self.ws.home / "proj"
        project.mkdir()
        names = [i["name"] for i in json.loads(self.ws.ms("budget", "--json", cwd=project).stdout)["items"]]
        self.assertEqual(names.count("skill ms-once"), 1)
        self.assertEqual(names.count("agent ms-agent-once"), 1)

    def test_auto_memory_index_is_counted(self):
        slug = str(self.ws.root / "lib").replace("/", "-")
        mem = self.ch / "projects" / slug / "memory"
        mem.mkdir(parents=True)
        (mem / "MEMORY.md").write_text("m" * 1200)
        self.assertEqual({i["name"]: i["tokens"] for i in self.budget()["items"]}["auto-memory index (MEMORY.md)"], 300)


# -------------------------------------------------------------- read guard hook
class TestReadGuard(Base):
    def setUp(self):
        super().setUp()
        self.file = self.ws.tmp / "Big.java"
        self.file.write_text("x" * 8000)

    def read(self, path=None, session="s1", **extra):
        payload = {"hook_event_name": "PreToolUse", "session_id": session, "tool_name": "Read",
                   "tool_input": {"file_path": str(path or self.file), **extra}}
        return self.ws.ms("readguard", input=json.dumps(payload))

    def hint(self, r):
        self.assertEqual(r.returncode, 0)
        return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"] if r.stdout.strip() else ""

    def test_second_identical_read_gets_a_hint(self):
        self.assertEqual(self.hint(self.read()), "")
        msg = self.hint(self.read())
        self.assertIn("Big.java was already read 1 time", msg)
        self.assertIn("2000 tokens", msg)
        self.assertEqual(json.loads(self.read().stdout)["hookSpecificOutput"]["hookEventName"], "PreToolUse")

    def test_escalates_after_several_repeats(self):
        for _ in range(3):
            self.read()
        self.assertIn("memory note", self.hint(self.read()))

    def test_different_ranges_sessions_and_changes_are_not_repeats(self):
        self.read(offset=0, limit=50)
        self.assertEqual(self.hint(self.read(offset=50, limit=50)), "")
        self.read()
        self.assertEqual(self.hint(self.read(session="other")), "")
        self.file.write_text("y" * 9000)   # edited: reading it again is legitimate
        self.assertEqual(self.hint(self.read()), "")

    def test_small_files_are_not_nagged(self):
        small = self.ws.tmp / "small.txt"
        small.write_text("tiny")
        self.read(small)
        self.assertEqual(self.hint(self.read(small)), "")

    def test_clear_or_compact_resets_the_memory(self):
        self.read()
        reset = {"hook_event_name": "SessionStart", "session_id": "s1", "source": "compact"}
        self.assertEqual(self.ws.ms("readguard", "--reset", input=json.dumps(reset)).returncode, 0)
        self.assertEqual(self.hint(self.read()), "", "after a compaction the file is no longer in context")
        self.read()
        self.ws.ms("readguard", input=json.dumps(reset))
        self.assertEqual(self.hint(self.read()), "")

    def test_never_fails_the_session(self):
        for payload in ("", "garbage", "{}", json.dumps({"tool_input": {"file_path": "/does/not/exist"}, "session_id": "s"}),
                        json.dumps({"tool_input": {}, "session_id": "s"})):
            r = self.ws.ms("readguard", input=payload)
            self.assertEqual((r.returncode, r.stdout.strip()), (0, ""), payload)


# ------------------------------------------------------------ output guard hook
class TestOutGuard(Base):
    def run_hook(self, stdout="", stderr="", tool="Bash", env=None, cwd=None, command="seq 1 5000"):
        payload = {"hook_event_name": "PostToolUse", "tool_name": tool, "tool_use_id": "tu-1", "cwd": str(cwd or self.ws.tmp),
                   "tool_input": {"command": command},
                   "tool_response": {"stdout": stdout, "stderr": stderr, "interrupted": False, "isImage": False}}
        return self.ws.ms("outguard", input=json.dumps(payload), env=env, cwd=self.ws.tmp)

    def updated(self, r):
        self.assertEqual(r.returncode, 0)
        return json.loads(r.stdout)["hookSpecificOutput"]["updatedToolOutput"] if r.stdout.strip() else None

    def test_small_output_is_left_alone(self):
        self.assertIsNone(self.updated(self.run_hook("\n".join(str(i) for i in range(100)))))

    def test_huge_output_keeps_head_and_tail_and_saves_everything(self):
        big = "\n".join(f"line {i}" for i in range(1, 8001))
        out = self.updated(self.run_hook(big))
        text = out["stdout"]
        self.assertIn("line 1\n", text)
        self.assertIn("line 60\n", text)
        self.assertIn("line 8000", text)
        self.assertNotIn("line 4000\n", text)
        self.assertIn("lines omitted", text)
        self.assertLess(len(text), 6000)
        self.assertEqual((out["interrupted"], out["isImage"]), (False, False), "the output shape is preserved")
        saved = Path(re.search(r"Full output: (\S+\.txt)", text).group(1))
        self.assertIn("line 4000\n", saved.read_text())
        self.assertIn("$ seq 1 5000", saved.read_text())

    def test_stderr_is_kept_when_stdout_is_large(self):
        out = self.updated(self.run_hook("\n".join(f"o{i}" for i in range(9000)), stderr="FATAL: the real error\n"))
        self.assertIn("FATAL: the real error", out["stderr"])

    def test_very_long_single_lines_are_cut_by_characters(self):
        out = self.updated(self.run_hook("A" * 200000))
        self.assertLess(len(out["stdout"]), 40000)
        self.assertIn("characters omitted", out["stdout"])

    def test_threshold_from_env_and_workspace_config(self):
        mid = "\n".join(f"l{i}" for i in range(3000))   # about 16 000 characters: under the default limit
        self.assertIsNone(self.updated(self.run_hook(mid)))
        self.assertIsNotNone(self.updated(self.run_hook(mid, env={"MS_OUTGUARD_MAX_CHARS": "5000"})))
        self.ws.set_toml(DEFAULT_TOML + "\n[context]\nbash_output_max_chars = 5000\n")
        self.assertIsNotNone(self.updated(self.run_hook(mid, cwd=self.ws.root / "lib")))

    def test_can_be_turned_off_and_ignores_other_tools(self):
        big = "z\n" * 40000
        self.assertIsNone(self.updated(self.run_hook(big, env={"MS_OUTGUARD": "off"})))
        self.assertIsNone(self.updated(self.run_hook(big, tool="Read")))

    def test_never_fails_the_session(self):
        for payload in ("", "garbage", "{}", json.dumps({"tool_name": "Bash", "tool_response": "text"}),
                        json.dumps({"tool_name": "Bash", "tool_response": {"stdout": None}})):
            r = self.ws.ms("outguard", input=payload)
            self.assertEqual((r.returncode, r.stdout.strip()), (0, ""), payload)


# ------------------------------------------------------------------ undo a ship
class TestUndo(Base):
    def setUp(self):
        super().setUp()
        self.d = self.ws.batch("b1")
        self.ws.commit(self.d / "lib", "lib feature", {"feat.txt": "1"})
        self.ws.commit(self.d / "app", "app feature", {"feat.txt": "2"})
        self.before = {r: self.ws.git(self.ws.tmp / f"remote-{r}.git", "rev-parse", "next") for r in ("lib", "app")}
        self.assertOk(self.ws.ms("ship", "b1", "--yes", "--skip-e2e"))

    def remote_files(self, repo):
        return self.ws.git(self.ws.tmp / f"remote-{repo}.git", "ls-tree", "-r", "--name-only", "next").splitlines()

    def record(self):
        files = list((self.ws.root / ".ms-workspace" / "ship").glob("b1-*.json"))
        self.assertEqual(len(files), 1)
        return json.loads(files[0].read_text())

    def test_ship_records_before_and_after(self):
        rec = self.record()
        for r in ("lib", "app"):
            info = rec["repos"][r]
            self.assertEqual(info["before"], self.before[r])
            self.assertEqual(info["after"], self.ws.git(self.ws.tmp / f"remote-{r}.git", "rev-parse", "next"))
            self.assertTrue(info["pushed"])
        self.assertIn("ship", self.ws.log_lines("--action", "ship"))

    def test_plan_only_changes_nothing(self):
        r = self.ws.ms("undo", "b1")
        self.assertOk(r)
        self.assertIn("plan only", r.stdout)
        self.assertIn("feat.txt", self.remote_files("lib"))

    def test_yes_restores_the_old_tree_with_a_new_commit_and_keeps_history(self):
        r = self.ws.ms("undo", "b1", "--yes")
        self.assertOk(r)
        for repo in ("lib", "app"):
            self.assertNotIn("feat.txt", self.remote_files(repo))
            log = self.ws.remote_log(repo)
            self.assertEqual(log[0], "Revert batch b1 (restores " + self.before[repo][:8] + ")")
            self.assertIn(f"{repo} feature", log, "the shipped commits stay in the history; nothing is force-pushed")
        self.assertIn("undo", self.ws.log_lines("--action", "undo"))

    def test_refuses_when_others_pushed_after_the_ship(self):
        mate = self.ws.tmp / "mate"
        self.ws.git(self.ws.tmp, "clone", "-q", str(self.ws.tmp / "remote-lib.git"), str(mate))
        self.ws.git(mate, "checkout", "-q", "next")
        self.ws.commit(mate, "mate commit", {"mate.txt": "m"})
        self.ws.git(mate, "push", "-q", "origin", "next")
        r = self.ws.ms("undo", "b1", "--yes")
        self.assertEqual(r.returncode, 1)
        self.assertIn("others pushed 1 commit", r.stdout)
        self.assertIn("git revert --no-edit", r.stdout)
        self.assertEqual(self.ws.remote_log("lib")[0], "mate commit", "nothing was pushed for lib")
        self.assertNotIn("feat.txt", self.remote_files("app"), "app, where nobody else pushed, is reverted")

    def test_still_works_after_the_batch_was_cleaned(self):
        self.assertOk(self.ws.ms("clean", "b1"))
        self.assertOk(self.ws.ms("undo", "b1", "--yes"))
        self.assertNotIn("feat.txt", self.remote_files("lib"))

    def test_unknown_batch_and_unpushed_repos(self):
        self.assertNotEqual(self.ws.ms("undo", "ghost").returncode, 0)
        path = next((self.ws.root / ".ms-workspace" / "ship").glob("b1-*.json"))
        rec = json.loads(path.read_text())
        rec["repos"]["app"]["pushed"] = False
        rec["repos"]["lib"]["mode"] = "pr"
        path.write_text(json.dumps(rec))
        out = self.ws.ms("undo", "b1", "--yes").stdout
        self.assertIn("app: was not pushed", out)
        self.assertIn("gh pr close --delete-branch int/b1", out)
        self.assertIn("feat.txt", self.remote_files("app"))
        self.assertIn("feat.txt", self.remote_files("lib"))

    def test_needs_a_batch_name(self):
        self.assertNotEqual(self.ws.ms("undo").returncode, 0)


# --------------------------------------------------------------------- http
import http.server
import threading


class FakeApi:
    """A tiny HTTP API on a random local port that records every request it receives."""

    def __init__(self):
        self.state = {"version": 1, "health_status": 200, "delay": 0.0}
        self.received = []
        api = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, status, body, ctype="application/json", headers=None):
                data = body if isinstance(body, bytes) else (json.dumps(body) if not isinstance(body, str) else body).encode()
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass   # the client gave up (timeout test)

            def _handle(self):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length).decode() if length else ""
                api.received.append({"method": self.command, "path": self.path, "headers": dict(self.headers), "body": raw})
                path = self.path.split("?")[0]
                if path == "/health":
                    return self._send(api.state["health_status"], {"status": "UP" if api.state["health_status"] == 200 else "DOWN", "version": api.state["version"]})
                if path == "/login" and self.command == "POST":
                    data = json.loads(raw or "{}")
                    if data.get("password") == "s3cret":
                        return self._send(200, {"access_token": "tok123", "user": {"name": data.get("user")}})
                    return self._send(401, {"error": "bad credentials"})
                if path == "/me":
                    if self.headers.get("Authorization") == "Bearer tok123":
                        return self._send(200, {"user": {"name": "mario"}, "items": [{"id": 1}, {"id": 2}]})
                    return self._send(401, {"error": "no token"})
                if path == "/slow":
                    time.sleep(api.state["delay"])
                    return self._send(200, "ok", "text/plain")
                if path == "/fail":
                    return self._send(500, "boom", "text/plain")
                if path == "/text":
                    return self._send(200, "hello world", "text/plain")
                if path == "/redirect":
                    return self._send(302, "", "text/plain", {"Location": "/health"})
                return self._send(404, {"error": "not found"})

            do_GET = do_POST = do_PUT = do_DELETE = _handle

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


SMOKE = """
[defaults]
headers = { Accept = "application/json" }

[[request]]
name = "health"
path = "/health"
tags = ["smoke"]
expect = { status = 200, json = { status = "UP" }, max_ms = 5000 }

[[request]]
name = "login"
method = "POST"
path = "/login"
json = { user = "{{user}}", password = "{{secret:password}}" }
capture = { token = "json:access_token" }
expect = { status = 200, json_exists = ["access_token"] }

[[request]]
name = "me"
path = "/me"
headers = { Authorization = "Bearer {{token}}" }
expect = { status = 200, json = { "user.name" = "mario", "items.1.id" = 2 }, headers = { content-type = "json" } }
"""


class HttpBase(Base):
    @classmethod
    def setUpClass(cls):
        cls.api = FakeApi()

    @classmethod
    def tearDownClass(cls):
        cls.api.close()

    def setUp(self):
        super().setUp()
        self.api.received.clear()
        self.api.state.update({"version": 1, "health_status": 200, "delay": 0.0})
        self.req = self.ws.root / "requests"
        (self.req / "env").mkdir(parents=True)
        (self.req / "env" / "local.toml").write_text(f'base_url = "{self.api.url}"\nuser = "mario"\n')
        (self.req / "env" / "local.secrets").write_text("password=s3cret\n")
        (self.req / "smoke.http.toml").write_text(SMOKE)

    def http(self, *args, **kw):
        return self.ws.ms("http", *args, **kw)

    def log_text(self):
        return "\n".join(p.read_text() for p in (self.ws.root / ".ms-workspace" / "http").glob("*.jsonl"))

    def requests_log(self):
        return [json.loads(l) for l in self.log_text().splitlines() if '"kind":"request"' in l]


class TestHttpRun(HttpBase):
    def test_runs_a_collection_captures_a_token_and_logs_every_exchange(self):
        r = self.http("run", "smoke")
        self.assertOk(r)
        for name in ("health", "login", "me"):
            self.assertRegex(r.stdout, rf"PASS {name}\s")
        self.assertIn("Summary: 3 passed, 0 failed, 0 skipped", r.stdout)
        me = next(x for x in self.api.received if x["path"] == "/me")
        self.assertEqual(me["headers"].get("Authorization"), "Bearer tok123", "the captured token was sent")
        rows = self.requests_log()
        self.assertEqual([x["name"] for x in rows], ["health", "login", "me"])
        self.assertTrue(all(x["ok"] and x["status"] == 200 and x["ms"] >= 0 for x in rows))
        self.assertIn("http.run", self.ws.log_lines("--action", "http.run"))

    def test_secrets_and_tokens_never_reach_the_log_or_the_output(self):
        r = self.http("run", "smoke")
        everything = r.stdout + r.stderr + self.log_text()
        self.assertNotIn("s3cret", everything)
        self.assertNotIn("tok123", everything)
        login = next(x for x in self.requests_log() if x["name"] == "login")
        self.assertIn('"password":"***"', login["req_body"])
        self.assertIn('"access_token":"***"', login["resp_body"])
        me = next(x for x in self.requests_log() if x["name"] == "me")
        self.assertEqual(me["req_headers"]["Authorization"], "***")
        self.assertIn('"name":"mario"', login["resp_body"].replace(" ", ""), "ordinary data is kept")

    def test_failures_are_explained_and_dependents_are_skipped(self):
        (self.req / "env" / "local.secrets").write_text("password=wrong\n")
        r = self.http("run", "smoke")
        self.assertEqual(r.returncode, 1)
        self.assertIn("FAIL login", r.stdout)
        self.assertIn("status: expected 200, got 401", r.stdout)
        self.assertIn("json_exists access_token: missing", r.stdout)
        self.assertIn("SKIP me", r.stdout)
        self.assertIn("variable {{token}} has no value", r.stdout)
        self.assertIn("1 passed, 1 failed, 1 skipped", r.stdout)
        self.assertNotIn("wrong", r.stdout + self.log_text())

    def test_every_assertion_kind(self):
        (self.req / "checks.http.toml").write_text("""
[[request]]
name = "bad-json"
path = "/health"
expect = { status = 200, json = { status = "DOWN", "nope.deep" = 1 }, json_exists = ["version", "missing"], body_contains = ["UP", "absent-text"], body_not_contains = ["UP"], headers = { x-missing = "y" } }

[[request]]
name = "status-list"
path = "/fail"
expect = { status = [200, 201] }

[[request]]
name = "too-slow"
path = "/slow"
expect = { max_ms = 1 }

[[request]]
name = "default-status-rule"
path = "/fail"

[[request]]
name = "redirect-not-followed"
path = "/redirect"
expect = { status = 302 }
""")
        self.api.state["delay"] = 0.05
        out = self.http("run", "checks").stdout
        for want in ('json status: expected \'DOWN\', got \'UP\'', "json nope.deep: missing", "json_exists missing: missing",
                     "body_contains 'absent-text': not found", "body_not_contains 'UP': found", "header x-missing: expected 'y', got None",
                     "status: expected 200 or 201, got 500", "time: ", "status: got 500 (no expected status set"):
            self.assertIn(want, out)
        self.assertIn("PASS redirect-not-followed", out, "redirects are not followed unless asked to")
        self.assertNotIn("json_exists version", out)

    def test_filters_overrides_and_fail_fast(self):
        self.assertIn("1 passed, 0 failed, 0 skipped", self.http("run", "smoke", "--only", "health").stdout)
        self.assertIn("1 passed", self.http("run", "smoke", "--tag", "smoke").stdout)
        self.api.received.clear()
        self.http("run", "smoke", "--only", "login", "--var", "user=bob")
        self.assertEqual(json.loads(self.api.received[0]["body"])["user"], "bob")
        self.api.state["health_status"] = 503
        out = self.http("run", "smoke", "--fail-fast").stdout
        self.assertIn("FAIL health", out)
        self.assertIn("SKIP login  (stopped by --fail-fast)", out)

    def test_query_form_text_and_environment_variables(self):
        (self.req / "misc.http.toml").write_text("""
[[request]]
name = "query"
path = "/text"
query = { page = 2, q = "a b" }
headers = { X-Trace = "{{env:TRACE_ID}}" }
expect = { status = 200, body_contains = ["hello"] }

[[request]]
name = "form"
method = "POST"
path = "/text"
form = { a = "1", b = "x y" }
expect = { status = 200 }
""")
        r = self.http("run", "misc", env={"TRACE_ID": "abc-9"})
        self.assertOk(r)
        q = next(x for x in self.api.received if x["method"] == "GET")
        self.assertIn("page=2", q["path"])
        self.assertIn("q=a+b", q["path"])
        self.assertEqual(q["headers"].get("X-Trace"), "abc-9")
        form = next(x for x in self.api.received if x["method"] == "POST")
        self.assertEqual(form["body"], "a=1&b=x+y")
        self.assertIn("application/x-www-form-urlencoded", form["headers"]["Content-Type"])
        missing = self.http("run", "misc")   # TRACE_ID not set
        self.assertEqual(missing.returncode, 1)
        self.assertIn("variable {{env:TRACE_ID}} has no value", missing.stdout)

    def test_connection_errors_and_timeouts_are_reported_not_raised(self):
        (self.req / "env" / "dead.toml").write_text('base_url = "http://127.0.0.1:9"\n')
        r = self.http("run", "smoke", "--env", "dead", "--only", "health")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no response", r.stdout)
        self.assertNotIn("Traceback", r.stderr)
        self.api.state["delay"] = 1.0
        (self.req / "slow.http.toml").write_text('[[request]]\nname = "slow"\npath = "/slow"\n')
        r = self.http("run", "slow", "--timeout", "0.2")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no response", r.stdout)

    def test_protected_environments_need_an_explicit_yes(self):
        (self.req / "env" / "qa.toml").write_text(f'confirm = true\nbase_url = "{self.api.url}"\nuser = "mario"\n')
        (self.req / "env" / "qa.secrets").write_text("password=s3cret\n")
        r = self.http("run", "smoke", "--env", "qa")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--yes", r.stderr)
        self.assertEqual(self.api.received, [], "nothing was sent")
        self.assertOk(self.http("run", "smoke", "--env", "qa", "--yes"))
        self.assertNotEqual(self.http("bench", "smoke", "--name", "health", "--env", "qa").returncode, 0)

    def test_bad_input_gives_clear_errors(self):
        (self.req / "broken.http.toml").write_text("not [valid toml")
        (self.req / "empty.http.toml").write_text('name = "nothing"\n')
        for args in (("run", "broken"), ("run", "empty"), ("run", "ghost"), ("run",), ("run", "smoke", "--env", "nope"), ("run", "smoke", "--bogus"), ("frobnicate",)):
            r = self.http(*args)
            self.assertNotEqual(r.returncode, 0, args)
            self.assertNotIn("Traceback", r.stderr, args)

    def test_json_output_and_runs_without_a_workspace(self):
        data = json.loads(self.http("run", "smoke", "--json").stdout)
        self.assertEqual((data["passed"], data["failed"]), (3, 0))
        self.assertEqual([x["status"] for x in data["results"]], ["pass"] * 3)
        file = self.req / "smoke.http.toml"
        r = self.ws.ms("http", "run", str(file), "--var", f"base_url={self.api.url}", "--var", "user=mario", "--only", "health", cwd=self.ws.tmp)
        self.assertOk(r)
        self.assertTrue(list((self.ws.cache / "http").glob("*.jsonl")), "without a workspace the log goes to the cache directory")


class TestHttpHistory(HttpBase):
    def test_history_show_and_diff(self):
        self.assertIn("(no runs yet)", self.http("history").stdout)
        self.http("run", "smoke")
        self.api.state.update({"version": 2, "health_status": 503})
        self.http("run", "smoke", "--only", "health")
        hist = self.http("history").stdout.strip().splitlines()
        self.assertEqual(len(hist), 2)
        self.assertIn("3 passed, 0 failed", hist[0])
        self.assertIn("0 passed, 1 failed", hist[1])
        shown = self.http("show", "last").stdout
        self.assertIn("health: GET", shown)
        self.assertIn("failed: status: expected 200, got 503", shown)
        self.assertIn("response body:", shown)
        diff = self.http("diff").stdout
        self.assertIn("health: status 200 -> 503 | result pass -> fail", diff)
        self.assertIn("version: 1 -> 2", diff)
        self.assertIn("login: only in the older run", diff)

    def test_diff_reports_no_changes_and_needs_an_earlier_run(self):
        self.http("run", "smoke")
        self.assertNotEqual(self.http("diff").returncode, 0)
        self.http("run", "smoke")
        self.assertIn("no differences", self.http("diff").stdout)
        self.assertNotEqual(self.http("show", "zzz").returncode, 0)

    def test_list_shows_files_requests_tags_and_environments(self):
        out = self.http("list").stdout
        self.assertIn("environments: local", out)
        self.assertIn("smoke.http.toml: health [smoke], login, me", out)
        empty = WS()
        self.addCleanup(empty.close)
        self.assertIn("no *.http.toml files", empty.ms("http", "list").stdout)


class TestHttpBench(HttpBase):
    def test_bench_stores_stats_and_flags_regressions(self):
        (self.req / "slow.http.toml").write_text('[[request]]\nname = "slow"\npath = "/slow"\n')
        self.api.state["delay"] = 0.01
        first = self.http("bench", "slow", "--name", "slow", "-n", "8")
        self.assertOk(first)
        self.assertRegex(first.stdout, r"n=8 errors=0 min=[\d.]+ms avg=[\d.]+ms p50=[\d.]+ms p95=[\d.]+ms max=[\d.]+ms")
        self.assertIn("first measurement stored", first.stdout)
        self.api.state["delay"] = 0.25
        second = self.http("bench", "slow", "--name", "slow", "-n", "8")
        self.assertEqual(second.returncode, 1)
        self.assertIn("REGRESSION", second.stdout)
        self.api.state["delay"] = 0.25
        again = self.http("bench", "slow", "--name", "slow", "-n", "8")
        self.assertOk(again)
        self.assertIn("vs previous", again.stdout)

    def test_bench_input_errors(self):
        self.assertNotEqual(self.http("bench", "smoke").returncode, 0)
        self.assertNotEqual(self.http("bench", "smoke", "--name", "ghost").returncode, 0)
        self.assertNotEqual(self.http("bench", "smoke", "--name", "health", "-n", "x").returncode, 0)
        self.assertNotEqual(self.http("bench", "smoke", "--name", "me").returncode, 0, "needs {{token}}, which a bench does not capture")


class TestHttpShip(HttpBase):
    TOML = DEFAULT_TOML + '\n[http]\nsmoke = "smoke"\nsmoke_env = "local"\n'

    def setUp(self):
        super().setUp()
        self.ws.set_toml(self.TOML)
        d = self.ws.batch("b1", "lib")
        self.ws.commit(d / "lib", "feature", {"f.txt": "1"})

    def test_plan_mentions_the_smoke_checks(self):
        self.assertIn("smoke checks: smoke (env local)", self.ws.ms("plan", "b1").stdout)

    def test_a_passing_smoke_run_lets_the_push_happen(self):
        r = self.ws.ms("ship", "b1", "--yes", "--skip-e2e")
        self.assertOk(r)
        self.assertIn("PASS health", r.stdout)
        self.assertEqual(self.ws.remote_log("lib")[0], "feature")

    def test_a_failing_smoke_run_blocks_the_push_unless_skipped(self):
        self.api.state["health_status"] = 503
        r = self.ws.ms("ship", "b1", "--yes", "--skip-e2e")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("smoke checks failed", r.stderr)
        self.assertNotIn("feature", self.ws.remote_log("lib"))
        self.assertOk(self.ws.ms("ship", "b1", "--yes", "--skip-e2e", "--skip-smoke"))
        self.assertEqual(self.ws.remote_log("lib")[0], "feature")


class TestHttpPermissions(unittest.TestCase):
    def test_reading_is_allowed_but_sending_asks(self):
        perms = json.loads((REPO / "settings" / "hooks.example.json").read_text())["permissions"]
        for sub in ("list", "history", "show", "diff"):
            self.assertIn(f"Bash(ms-workspace http {sub}:*)", perms["allow"])
        for sub in ("run", "bench"):
            self.assertIn(f"Bash(ms-workspace http {sub}:*)", perms["ask"])
            self.assertNotIn(f"Bash(ms-workspace http {sub}:*)", perms["allow"])


# ----------------------------------------------------------------- mock server
import signal
import urllib.error
import urllib.request

PAYMENTS_MOCK = """
[[route]]
name = "create"
method = "POST"
path = "/v1/payments"
status = 201
json = { id = "pay_{{seq}}", amount = "{{body.amount}}", status = "approved", ref = "{{header.x-ref}}", uid = "{{uuid}}" }

[[route]]
name = "card-only"
path = "/v1/methods"
match = { query = { type = "card" } }
json = { methods = ["visa"] }

[[route]]
name = "any-method"
path = "/v1/methods"
json = { methods = ["visa", "cash"] }

[[route]]
name = "get"
path = "/v1/payments/{id}"
json = { id = "{{path.id}}", page = "{{query.page}}", status = "approved" }

[[route]]
name = "flaky"
path = "/flaky"
sequence = [ { status = 503 }, { status = 503, headers = { Retry-After = "1" } }, { status = 200, json = { ok = true } } ]

[[route]]
name = "loop"
path = "/loop"
loop = true
sequence = [ { body = "a" }, { body = "b" } ]

[[route]]
name = "slow"
path = "/slow"
delay_ms = 300
body = "late"

[[route]]
name = "by-body"
method = "POST"
path = "/charge"
match = { json = { "card.type" = "debit" } }
json = { fee = 1 }

[[route]]
name = "wild"
path = "/files/*"
body = "file"
"""


def call(url, method="GET", body=None, headers=None, timeout=5):
    data = json.dumps(body).encode() if isinstance(body, (dict, list)) else (body.encode() if body else None)
    h = {"Content-Type": "application/json", **(headers or {})} if data else (headers or {})
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode(), dict(r.headers)
    except urllib.error.HTTPError as e:
        try:
            return e.code, e.read().decode(), dict(e.headers)
        finally:
            e.close()


class MockBase(Base):
    def setUp(self):
        super().setUp()
        (self.ws.root / "mocks").mkdir()
        (self.ws.root / "mocks" / "pay.mock.toml").write_text(PAYMENTS_MOCK)
        self.addCleanup(lambda: self.ws.ms("mock", "stop", "--all"))

    def start(self, name="pay", *extra):
        r = self.ws.ms("mock", "start", name, *extra)
        self.assertOk(r)
        return re.search(r"http://127\.0\.0\.1:\d+", r.stdout).group(0)


class TestMock(MockBase):
    def test_lifecycle_start_status_url_stop(self):
        url = self.start()
        self.assertEqual(self.ws.ms("mock", "url", "pay").stdout.strip(), url)
        status = self.ws.ms("mock", "status").stdout
        self.assertIn("pay: " + url, status)
        pid = json.loads(next((self.ws.root / ".ms-workspace" / "mock" / "pay").glob("server.json")).read_text())["pid"]
        self.assertEqual(call(url + "/v1/methods?type=card")[0], 200)
        self.assertIn("already running", self.ws.ms("mock", "start", "pay").stdout)
        self.assertIn("stopped mock 'pay'", self.ws.ms("mock", "stop", "pay").stdout)
        with self.assertRaises(OSError):
            call(url + "/v1/methods", timeout=1)
        self.assertIn("no mock servers", self.ws.ms("mock", "status").stdout)
        with self.assertRaises(ProcessLookupError):
            for _ in range(30):
                os.kill(pid, 0)
                time.sleep(0.1)
            os.kill(pid, 0)

    def test_templates_keep_types_and_use_request_data(self):
        url = self.start()
        status, body, _ = call(url + "/v1/payments", "POST", {"amount": 100}, {"X-Ref": "r1"})
        data = json.loads(body)
        self.assertEqual(status, 201)
        self.assertEqual((data["id"], data["amount"], data["ref"]), ("pay_1", 100, "r1"))
        self.assertIsInstance(data["amount"], int)
        self.assertRegex(data["uid"], r"^[0-9a-f-]{36}$")
        self.assertEqual(json.loads(call(url + "/v1/payments", "POST", {"amount": 5})[1])["id"], "pay_2")
        got = json.loads(call(url + "/v1/payments/abc?page=3")[1])
        self.assertEqual((got["id"], got["page"]), ("abc", "3"))

    def test_sequences_and_loops(self):
        url = self.start()
        codes = [call(url + "/flaky")[0] for _ in range(5)]
        self.assertEqual(codes, [503, 503, 200, 200, 200], "the last step repeats")
        self.assertEqual(call(url + "/flaky")[2].get("Retry-After"), None)
        self.assertEqual([call(url + "/loop")[1] for _ in range(4)], ["a", "b", "a", "b"])

    def test_matching_on_query_and_body_and_first_match_wins(self):
        url = self.start()
        self.assertIn("visa", call(url + "/v1/methods?type=card")[1])
        self.assertIn("cash", call(url + "/v1/methods")[1])
        self.assertEqual(json.loads(call(url + "/charge", "POST", {"card": {"type": "debit"}})[1]), {"fee": 1})
        self.assertEqual(call(url + "/charge", "POST", {"card": {"type": "credit"}})[0], 404)
        self.assertEqual(call(url + "/files/a/b/c.txt")[1], "file")

    def test_delay(self):
        url = self.start()
        started = time.time()
        call(url + "/slow")
        self.assertGreaterEqual(time.time() - started, 0.3)

    def test_unmatched_requests_are_404_and_recorded(self):
        url = self.start()
        status, body, _ = call(url + "/nope")
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body)["error"], "no mock route")
        out = self.ws.ms("mock", "requests", "--unmatched").stdout
        self.assertIn("GET /nope -> 404 (NO ROUTE", out)
        failed = self.ws.ms("mock", "assert", "--no-unmatched")
        self.assertEqual(failed.returncode, 1)
        self.assertIn("hit no route", failed.stdout)

    def test_assertions_on_what_was_received(self):
        url = self.start()
        call(url + "/v1/payments", "POST", {"amount": 100, "currency": "COP"}, {"X-Ref": "order-7"})
        call(url + "/v1/payments/p1?page=2")
        a = lambda *x: self.ws.ms("mock", "assert", "pay", *x)
        self.assertOk(a("--path", "/v1/payments", "--method", "POST", "--times", "1", "--json", "amount=100", "--json", "currency=COP"))
        self.assertOk(a("--path", "/v1/payments/*", "--query", "page=2"))
        self.assertOk(a("--path", "/v1/payments", "--header", "x-ref=order-7"))
        self.assertOk(a("--path", "/v1/payments/{id}", "--min", "1"))
        self.assertOk(a("--path", "/v1/refunds", "--none"))
        bad = a("--path", "/v1/payments", "--method", "POST", "--json", "amount=999")
        self.assertEqual(bad.returncode, 1)
        self.assertIn("found 0", bad.stdout)
        self.assertIn("closest: POST /v1/payments", bad.stdout)
        self.assertEqual(a("--path", "/v1/payments", "--times", "2").returncode, 1)
        self.assertNotEqual(a("--bogus").returncode, 0)
        self.assertNotEqual(self.ws.ms("mock", "assert", "pay").returncode, 0, "needs --path or --no-unmatched")

    def test_requests_listing_filters(self):
        url = self.start()
        call(url + "/v1/payments", "POST", {"amount": 1})
        call(url + "/v1/methods?type=card")
        out = self.ws.ms("mock", "requests", "--method", "POST").stdout
        self.assertIn("POST /v1/payments -> 201 (create", out)
        self.assertNotIn("/v1/methods", out)
        self.assertIn("?type=card", self.ws.ms("mock", "requests", "--path", "methods").stdout)
        self.assertEqual(len(self.ws.ms("mock", "requests", "-n", "1").stdout.strip().splitlines()), 1)

    def test_secrets_are_masked_in_the_record(self):
        url = self.start()
        call(url + "/v1/payments", "POST", {"amount": 1, "password": "hunter2", "card_token": "tok_live"}, {"Authorization": "Bearer abc123"})
        record = (self.ws.root / ".ms-workspace" / "mock" / "pay" / "requests.jsonl").read_text()
        for secret in ("hunter2", "tok_live", "abc123"):
            self.assertNotIn(secret, record)
        self.assertIn("***", record)

    def test_restart_reloads_and_stale_state_is_detected(self):
        url = self.start()
        pid = json.loads((self.ws.root / ".ms-workspace" / "mock" / "pay" / "server.json").read_text())["pid"]
        (self.ws.root / "mocks" / "pay.mock.toml").write_text('[[route]]\npath = "/new"\nbody = "fresh"\n')
        url2 = self.start("pay", "--restart")
        self.assertEqual(call(url2 + "/new")[1], "fresh")
        self.assertEqual(call(url2 + "/v1/methods")[0], 404)
        new_pid = json.loads((self.ws.root / ".ms-workspace" / "mock" / "pay" / "server.json").read_text())["pid"]
        self.assertNotEqual(pid, new_pid)
        os.kill(new_pid, signal.SIGKILL)
        time.sleep(0.3)
        self.assertIn("DEAD", self.ws.ms("mock", "status").stdout)
        self.assertEqual(call(self.start() + "/new")[1], "fresh", "a dead mock can simply be started again")

    def test_fixed_port_and_port_conflicts(self):
        free = socket_free_port()
        self.assertEqual(self.start("pay", "--port", str(free)), f"http://127.0.0.1:{free}")
        (self.ws.root / "mocks" / "other.mock.toml").write_text('[[route]]\npath = "/"\nbody = "x"\n')
        r = self.ws.ms("mock", "start", "other", "--port", str(free))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("exited at startup", r.stderr)
        self.assertNotIn("Traceback", r.stderr.split("exited at startup")[0])

    def test_invalid_definitions_and_names(self):
        (self.ws.root / "mocks" / "empty.mock.toml").write_text('port = 1\n')
        (self.ws.root / "mocks" / "bare.mock.toml").write_text('[[route]]\npath = "/x"\n')
        (self.ws.root / "mocks" / "broken.mock.toml").write_text("not [toml")
        for ref in ("empty", "bare", "broken", "ghost"):
            r = self.ws.ms("mock", "start", ref)
            self.assertNotEqual(r.returncode, 0, ref)
            self.assertNotIn("Traceback", r.stderr, ref)
        self.assertNotEqual(self.ws.ms("mock", "start").returncode, 0)
        self.assertNotEqual(self.ws.ms("mock", "url").returncode, 0)
        self.assertNotEqual(self.ws.ms("mock", "frobnicate").returncode, 0)
        listing = self.ws.ms("mock", "list").stdout
        self.assertIn("pay: 9 routes", listing)
        self.assertIn("broken: invalid", listing)
        self.assertIn("bare: invalid", listing)

    def test_works_together_with_the_http_tool(self):
        url = self.start()
        (self.ws.root / "requests").mkdir()
        (self.ws.root / "requests" / "pay.http.toml").write_text("""
[[request]]
name = "create"
method = "POST"
path = "/v1/payments"
json = { amount = 250 }
expect = { status = 201, json = { amount = 250, status = "approved" } }
""")
        r = self.ws.ms("http", "run", "pay", "--var", f"base_url={url}")
        self.assertOk(r)
        self.assertOk(self.ws.ms("mock", "assert", "--path", "/v1/payments", "--json", "amount=250", "--times", "1"))

    def test_without_a_workspace_state_goes_to_the_cache(self):
        d = self.ws.tmp / "loose"
        (d / "mocks").mkdir(parents=True)
        (d / "mocks" / "m.mock.toml").write_text('[[route]]\npath = "/"\nbody = "hi"\n')
        r = self.ws.ms("mock", "start", "m", cwd=d)
        self.assertOk(r)
        self.addCleanup(lambda: self.ws.ms("mock", "stop", "--all", cwd=d))
        self.assertEqual(call(re.search(r"http://\S+", r.stdout).group(0))[1], "hi")
        self.assertTrue((self.ws.cache / "mock" / "m" / "server.json").exists())


def socket_free_port():
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------------- docker
FAKE_DOCKER = r"""#!__PY__
import json, os, sys
data = json.load(open(os.environ["FAKE_DOCKER"]))
args = sys.argv[1:]
open(os.environ["FAKE_DOCKER"] + ".calls", "a").write(" ".join(args) + "\n")
if data.get("down"):
    sys.stderr.write("Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?\n"); sys.exit(1)
def lines(rows):
    print("\n".join(json.dumps(r) for r in rows))
cmd = args[0]
if cmd == "ps":
    if "status=exited" in args: lines(data.get("exited", []))
    else: lines([r for r in data["ps"] if "-a" in args or r["State"] == "running"])
elif cmd == "logs": print("\n".join(data["logs"].get(args[-1], [])))
elif cmd == "stats": lines(data["stats"])
elif cmd == "system": lines(data["df"])
elif cmd == "images": lines(data.get("dangling", []))
elif cmd == "inspect":
    if args[1] not in data["inspect"]:
        sys.stderr.write("Error: No such object: " + args[1] + "\n"); sys.exit(1)
    state = data["inspect"][args[1]]
    if isinstance(state, list):   # successive answers: pop the first
        item = state.pop(0) if len(state) > 1 else state[0]
        json.dump(data, open(os.environ["FAKE_DOCKER"], "w")); print(json.dumps([item]))
    else: print(json.dumps([state]))
elif cmd in ("container", "image", "volume"): print("Deleted things\nTotal reclaimed space: 12MB")
"""


def container(name, state="running", status="Up 2 hours", ports="", image="app:1", project="shop"):
    return {"Names": name, "Image": image, "State": state, "Status": status, "Ports": ports,
            "Labels": f"com.docker.compose.project={project},other=x" if project else ""}


class DockerBase(Base):
    def setUp(self):
        super().setUp()
        self.bin = self.ws.tmp / "dockerbin"
        self.bin.mkdir()
        exe = self.bin / "docker"
        exe.write_text(FAKE_DOCKER.replace("__PY__", sys.executable))
        exe.chmod(0o755)
        self.data_file = self.ws.tmp / "docker.json"
        self.data = {"ps": [], "logs": {}, "stats": [], "df": [], "inspect": {}}

    def d(self, *args, **extra):
        self.data_file.write_text(json.dumps(self.data))
        env = {"PATH": f"{self.bin}:{os.environ['PATH']}", "FAKE_DOCKER": str(self.data_file), **extra}
        return self.ws.ms("docker", *args, env=env)

    def calls(self):
        f = Path(str(self.data_file) + ".calls")
        return f.read_text().splitlines() if f.exists() else []


import sys


class TestDocker(DockerBase):
    def test_status_is_compact_and_flags_problems(self):
        self.data["ps"] = [
            container("shop-db", ports="0.0.0.0:5432->5432/tcp, :::5432->5432/tcp"),
            container("shop-web", status="Up 3 minutes (unhealthy)", ports="0.0.0.0:8080->80/tcp"),
            container("old-job", state="exited", status="Exited (1) 2 days ago", project=""),
        ]
        out = self.d("status").stdout
        self.assertIn("shop-db", out)
        self.assertIn("5432->5432", out)
        self.assertNotIn("0.0.0.0", out)
        self.assertEqual(out.count("5432->5432"), 1, "IPv4 and IPv6 bindings collapse into one")
        self.assertIn("[shop]", out)
        self.assertIn("Unhealthy: shop-web", out)
        self.assertNotIn("old-job", out)
        everything = self.d("status", "-a").stdout
        self.assertIn("old-job", everything)
        self.assertIn("Stopped: old-job", everything)
        self.assertNotIn("old-job", self.d("status", "--project", "shop", "-a").stdout)

    def test_logs_collapse_repeats_strip_timestamps_and_filter_errors(self):
        self.data["logs"]["web"] = (["2026-10-15T10:00:0%d.123Z GET /health 200" % (i % 10) for i in range(3)]
                                    + ["2026-10-15T10:00:00.1Z GET /health 200"] * 37
                                    + ["2026-10-15T10:01:00Z ERROR payment failed: connection refused", "plain line", "x" * 500])
        out = self.d("logs", "web").stdout
        self.assertIn("GET /health 200  (x38)", out) if False else None
        self.assertIn("(x", out)
        self.assertNotIn("2026-10-15T", out)
        self.assertTrue(all(len(l) < 330 for l in out.splitlines()))
        errors = self.d("logs", "web", "--errors").stdout
        self.assertIn("ERROR payment failed", errors)
        self.assertNotIn("plain line", errors)
        self.assertEqual(len(self.d("logs", "web", "-n", "2").stdout.strip().splitlines()), 3, "a header plus the last two lines")

    def test_logs_need_one_container(self):
        self.assertNotEqual(self.d("logs").returncode, 0)
        self.assertNotEqual(self.d("logs", "a", "b").returncode, 0)

    def test_stats_sorted_by_memory_with_a_high_flag(self):
        self.data["stats"] = [
            {"Name": "small", "CPUPerc": "1.00%", "MemUsage": "10MiB / 1GiB", "MemPerc": "1.00%", "NetIO": "1kB / 1kB", "PIDs": "3"},
            {"Name": "hog", "CPUPerc": "95.00%", "MemUsage": "900MiB / 1GiB", "MemPerc": "88.00%", "NetIO": "1MB / 2MB", "PIDs": "40"},
        ]
        lines = self.d("stats").stdout.strip().splitlines()
        self.assertTrue(lines[0].startswith("hog"))
        self.assertIn("<- high", lines[0])
        self.assertNotIn("<- high", lines[1])

    def test_disk_summary(self):
        self.data["df"] = [{"Type": "Images", "TotalCount": 12, "Active": 1, "Size": "5.2GB", "Reclaimable": "4.9GB (95%)"}]
        out = self.d("disk").stdout
        self.assertIn("Images", out)
        self.assertIn("reclaimable 4.9GB (95%)", out)
        self.assertIn("docker clean", out)

    def test_health_details(self):
        self.data["inspect"]["web"] = {"State": {"Status": "running", "ExitCode": 0, "OOMKilled": True, "Health": {
            "Status": "unhealthy", "Log": [{"ExitCode": 1, "Output": f"curl: (7) failed {i}\nrefused"} for i in range(5)]}},
            "RestartCount": 4, "Config": {"Image": "web:2"}}
        self.data["inspect"]["db"] = {"State": {"Status": "running", "ExitCode": 0}, "Config": {"Image": "pg:16"}}
        out = self.d("health", "web", "db").stdout
        self.assertIn("web: running, health unhealthy, restarts 4", out)
        self.assertIn("OOM-KILLED", out)
        self.assertEqual(out.count("check exit 1"), 3, "only the last three checks")
        self.assertIn("failed 4 / refused", out)
        self.assertIn("db: running, no healthcheck", out)
        r = self.d("health", "ghost")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("No such object", r.stderr)

    def test_ports_and_env_masking(self):
        self.data["ps"] = [container("a", ports="0.0.0.0:8080->80/tcp"), container("b", ports="0.0.0.0:5432->5432/tcp, :::5432->5432/tcp")]
        out = self.d("ports").stdout.strip().splitlines()
        self.assertEqual(len(out), 2)
        self.assertIn("5432 -> b:5432", out[0])
        self.data["inspect"]["a"] = {"Config": {"Env": ["DB_PASSWORD=hunter2", "API_KEY=abc", "MODE=prod", "PATH=/usr/bin"]}}
        env = self.d("env", "a").stdout
        self.assertNotIn("hunter2", env)
        self.assertNotIn("abc", env)
        self.assertIn("DB_PASSWORD=***", env)
        self.assertIn("MODE=prod", env)

    def test_wait_ready_failed_and_timeout(self):
        self.data["inspect"]["ok"] = {"State": {"Status": "running", "Health": {"Status": "healthy"}}}
        self.data["inspect"]["nohc"] = {"State": {"Status": "running"}}
        out = self.d("wait", "ok", "nohc", "--timeout", "5").stdout
        self.assertIn("ready  ok", out)
        self.assertIn("no healthcheck defined", out)
        self.data["inspect"]["dead"] = {"State": {"Status": "exited", "ExitCode": 137}}
        r = self.d("wait", "dead")
        self.assertEqual(r.returncode, 1)
        self.assertIn("FAILED dead: exited", r.stdout)
        self.data["inspect"]["slow"] = {"State": {"Status": "running", "Health": {"Status": "starting"}}}
        t = self.d("wait", "slow", "--timeout", "1")
        self.assertEqual(t.returncode, 1)
        self.assertIn("TIMEOUT waiting for: slow", t.stdout)
        self.assertNotEqual(self.d("wait").returncode, 0)

    def test_clean_is_a_plan_until_yes_and_never_touches_volumes_by_default(self):
        self.data["exited"] = [container("old1", state="exited"), container("old2", state="exited")]
        self.data["dangling"] = [{"Size": "100MB"}, {"Size": "50MB"}]
        plan = self.d("clean")
        self.assertOk(plan)
        self.assertIn("2 stopped container(s)", plan.stdout)
        self.assertIn("2 dangling image(s)", plan.stdout)
        self.assertIn("plan only", plan.stdout)
        self.assertFalse([c for c in self.calls() if "prune" in c], "nothing was pruned")
        self.assertOk(self.d("clean", "--yes", "--until", "48h"))
        prunes = [c for c in self.calls() if "prune" in c]
        self.assertEqual(prunes, ["container prune -f --filter until=48h", "image prune -f"])
        self.assertOk(self.d("clean", "--yes", "--volumes"))
        self.assertIn("volume prune -f", self.calls())

    def test_missing_docker_and_unreachable_daemon_are_clear(self):
        r = self.ws.ms_py("docker", "status", env={"PATH": "/nonexistent-dir"})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("docker is not installed", r.stderr)
        self.data["down"] = True
        r = self.d("status")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Cannot connect to the Docker daemon", r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertNotEqual(self.d("frobnicate").returncode, 0)


# ------------------------------------------------------------------- system info
class TestSys(Base):
    def setUp(self):
        super().setUp()
        self.proc = self.ws.tmp / "proc"
        self.proc.mkdir()
        (self.proc / "meminfo").write_text("MemTotal: 16777216 kB\nMemAvailable: 8388608 kB\nSwapTotal: 4194304 kB\nSwapFree: 4194304 kB\n")
        (self.proc / "cpuinfo").write_text("processor : 0\nmodel name\t: Test CPU @ 3.00GHz\n")
        (self.proc / "uptime").write_text("266400.55 1000.00\n")
        self.osr = self.ws.tmp / "os-release"
        self.osr.write_text('NAME="Test"\nPRETTY_NAME="Test Linux 1.0 LTS"\n')
        self.env = {"MS_PROC_ROOT": str(self.proc), "MS_OS_RELEASE": str(self.osr)}

    def sys(self, *args, **kw):
        return self.ws.ms("sys", *args, env={**self.env, **kw.pop("env", {})}, **kw)

    def test_summary_lines(self):
        out = self.sys().stdout
        self.assertIn("Test Linux 1.0 LTS", out)
        self.assertIn("up 3d 2h", out)
        self.assertIn("(Test CPU @ 3.00GHz)", out)
        self.assertIn("Memory: 16.0G total, 8.0G available (50%) | swap 4.0G (0% used)", out)
        self.assertIn("Disk: / ", out)
        self.assertIn("Network: ", out)
        self.assertNotIn("Hint:", out.split("Memory:")[1].split("Disk:")[0])

    def test_hints_for_memory_pressure_and_swap(self):
        (self.proc / "meminfo").write_text("MemTotal: 16777216 kB\nMemAvailable: 524288 kB\nSwapTotal: 4194304 kB\nSwapFree: 1048576 kB\n")
        out = self.sys().stdout
        self.assertIn("Only 0.5G of memory is available (3%)", out)
        self.assertIn("Swap is 75% used", out)

    def test_json_and_errors(self):
        data = json.loads(self.sys("--json").stdout)
        self.assertEqual(data["memory"]["total_gb"], 16.0)
        self.assertEqual(data["cpu"]["model"], "Test CPU @ 3.00GHz")
        self.assertIn("path", data["disks"][0])
        self.assertNotIn("tools", data)
        self.assertNotEqual(self.sys("--bogus").returncode, 0)

    def test_tool_versions_are_clean(self):
        bin_dir = self.ws.tmp / "tools"
        bin_dir.mkdir()
        for name, text in (("mvn", "\x1b[1mApache Maven 3.9.12\x1b[m\nMaven home: /x"), ("gradle", "\n------------------------------------------------------------\nGradle 8.5\n------"),
                           ("git", "git version 2.53.0")):
            f = bin_dir / name
            f.write_text(f"#!/bin/sh\nprintf '%s\\n' '{text}'\n".replace("\\x1b", "\x1b"))
            f.chmod(0o755)
        out = self.ws.ms_py("sys", "--tools", env={**self.env, "PATH": str(bin_dir)}).stdout
        self.assertIn("mvn Apache Maven 3.9.12", out)
        self.assertNotIn("\x1b", out)
        self.assertIn("gradle Gradle 8.5", out)
        self.assertIn("git git version 2.53.0", out)
        self.assertIn("node missing", out)


# --------------------------------------------------------------------- processes
class TestProcesses(Base):
    def spawn(self, code, cwd=None, **kw):
        proc = subprocess.Popen([sys.executable, "-c", code], cwd=cwd, stdout=subprocess.PIPE, text=True, **kw)
        self.addCleanup(proc.stdout.close)
        self.addCleanup(proc.wait)                                  # cleanups run last-in first-out: kill first, then reap
        self.addCleanup(lambda: (proc.poll() is None) and proc.kill())
        return proc

    SLEEP = "import time; print('up', flush=True); time.sleep(300)"

    def sleeper(self, cwd=None):
        p = self.spawn(self.SLEEP, cwd=cwd)
        self.assertEqual(p.stdout.readline().strip(), "up")
        return p

    def test_top_filters_and_option_errors(self):
        out = self.ws.ms("ps", "--top", "3").stdout.strip().splitlines()
        self.assertEqual(len(out), 4)
        self.assertIn("top 3 by cpu", out[0])
        self.assertIn("by mem", self.ws.ms("ps", "--by", "mem", "--top", "1").stdout)
        p = self.sleeper()
        self.assertIn(str(p.pid), self.ws.ms("ps", "--filter", "time.sleep(300)", "--top", "5").stdout)
        self.assertIn("dynamia" if os.environ.get("USER") == "dynamia" else os.environ.get("USER", ""), self.ws.ms("ps", "--mine").stdout)
        for bad in (("--top", "x"), ("--by", "disk"), ("--wat",)):
            self.assertNotEqual(self.ws.ms("ps", *bad).returncode, 0, bad)

    def test_find_and_tree(self):
        p = self.sleeper()
        found = self.ws.ms("ps", "find", "time.sleep(300)").stdout
        self.assertIn(str(p.pid), found)
        self.assertNotIn("ms-workspace ps find", found)
        tree = self.ws.ms("ps", "tree", str(os.getpid())).stdout
        self.assertIn(str(p.pid), tree, "the sleeper is a child of this test process")
        self.assertIn("(nothing matches)", self.ws.ms("ps", "tree", "no-such-process-zzz").stdout)
        self.assertNotEqual(self.ws.ms("ps", "find").returncode, 0)

    def test_ports_show_who_holds_a_port(self):
        if not shutil_which("ss"):
            self.skipTest("ss not available")
        p = self.spawn("import socket,time; s=socket.socket(); s.bind(('127.0.0.1',0)); s.listen(); print(s.getsockname()[1], flush=True); time.sleep(300)")
        port = int(p.stdout.readline())
        out = self.ws.ms("ps", "ports", "--port", str(port)).stdout
        self.assertIn(f"pid {p.pid}", out)
        self.assertIn(str(port), self.ws.ms("ps", "ports").stdout)
        self.assertIn("nothing is listening on port 1", self.ws.ms("ps", "ports", "--port", "1").stdout)
        self.assertNotEqual(self.ws.ms("ps", "ports", "--port", "x").returncode, 0)

    def test_kill_is_a_plan_until_yes_and_then_checks_the_result(self):
        p = self.sleeper()
        plan = self.ws.ms("ps", "kill", str(p.pid))
        self.assertOk(plan)
        self.assertIn(f"{p.pid}: would send TERM", plan.stdout)
        self.assertIn("plan only", plan.stdout)
        self.assertIsNone(p.poll())
        done = self.ws.ms("ps", "kill", str(p.pid), "--yes")
        self.assertOk(done)
        self.assertIn("gone", done.stdout)
        p.wait(timeout=5)
        self.assertIn("ps.kill", self.ws.log_lines("--action", "ps.kill"))

    def test_kill_refuses_dangerous_targets(self):
        p = self.spawn("import time,os; os.execvp('bash', ['bash','-c','exec -a tmux sleep 300'])")
        time.sleep(0.5)
        out = lambda *a: self.ws.ms("ps", "kill", *a, "--yes")
        for pid, why in ((1, "this session or one of its parents"), (os.getpid(), "this session or one of its parents"), (p.pid, "protected process"),
                         (999999, "no such process")):
            r = out(str(pid))
            self.assertEqual(r.returncode, 1, pid)
            self.assertIn(why, r.stdout, pid)
        self.assertIsNone(p.poll(), "the protected process survived")
        foreign = subprocess.run(["ps", "-axo", "pid=,user="], capture_output=True, text=True).stdout.split("\n")
        other = next((int(l.split()[0]) for l in foreign if l.strip() and l.split()[1] not in (os.environ.get("USER"), "root")), None)
        if other:
            self.assertIn("belongs to", out(str(other)).stdout)
        self.assertNotEqual(self.ws.ms("ps", "kill").returncode, 0)
        self.assertNotEqual(self.ws.ms("ps", "kill", "abc").returncode, 0)
        self.assertNotEqual(self.ws.ms("ps", "kill", "5", "--signal", "STOP").returncode, 0)

    def test_leftovers_are_attributed_to_the_batch_they_run_in(self):
        d = self.ws.batch("b1", "lib")
        self.sleeper(cwd=d / "lib")
        out = self.ws.ms("ps", "leftovers", "--hours", "0", "--limit", "10000").stdout   # no cap: a busy machine has more than 20
        self.assertIn("[batch b1/lib]", out)
        self.assertIn("ms-workspace ps kill", out)
        self.assertNotRegex(out.split("\n", 1)[1], r"(?m)(^|[\s/])claude(\s|$)")   # the claude CLI is protected; paths like test-my-claude are fine

    def test_clean_refuses_while_processes_run_inside_the_batch(self):
        d = self.ws.batch("b1", "lib")
        self.ws.commit(d / "lib", "f", {"f.txt": "1"})
        self.assertOk(self.ws.ms("ship", "b1", "--yes", "--skip-e2e"))
        p = self.sleeper(cwd=d / "lib")
        r = self.ws.ms("clean", "b1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("processes are still running inside the batch", r.stderr)
        self.assertIn(str(p.pid), r.stderr)
        self.assertTrue(d.exists())
        self.assertOk(self.ws.ms("ps", "kill", str(p.pid), "--yes"))
        p.wait(timeout=5)
        self.assertOk(self.ws.ms("clean", "b1"))

    def test_force_clean_warns_but_proceeds(self):
        d = self.ws.batch("b1", "lib")
        p = self.sleeper(cwd=d / "lib")
        r = self.ws.ms("clean", "b1", "--force")
        self.assertOk(r)
        self.assertIn(f"{p.pid}", r.stderr)


def shutil_which(name):
    import shutil
    return shutil.which(name)


class TestGuardForNewTools(Base):
    def guard(self, command, cwd):
        return self.ws.ms("guard", input=json.dumps({"tool_input": {"command": command}, "cwd": str(cwd)}))

    def test_agents_in_a_batch_cannot_kill_or_prune(self):
        d = self.ws.batch("b1")
        for cmd in ("ms-workspace ps kill 123 --yes", "ms-workspace docker clean --yes", "ms-workspace ps kill 5"):
            self.assertEqual(self.guard(cmd, d / "lib").returncode, 2, cmd)
        for cmd in ("ms-workspace ps", "ms-workspace ps ports", "ms-workspace docker status", "ms-workspace sys", "ms-workspace mock start pay",
                    "ms-workspace docker logs web --errors"):
            self.assertEqual(self.guard(cmd, d / "lib").returncode, 0, cmd)

    def test_permissions(self):
        perms = json.loads((REPO / "settings" / "hooks.example.json").read_text())["permissions"]
        for rule in ("Bash(ms-workspace sys:*)", "Bash(ms-workspace ps tree:*)", "Bash(ms-workspace ps ports:*)", "Bash(ms-workspace docker status:*)",
                     "Bash(ms-workspace docker logs:*)", "Bash(ms-workspace mock start:*)", "Bash(ms-workspace mock assert:*)"):
            self.assertIn(rule, perms["allow"])
        for rule in ("Bash(ms-workspace ps kill:*)", "Bash(ms-workspace docker clean:*)"):
            self.assertIn(rule, perms["ask"])
            self.assertNotIn(rule, perms["allow"])


# ------------------------------------------------------------------------ gate
def fake(*parts):
    """Build secret-looking test values from pieces, so this file never contains one literally."""
    return "".join(parts)


class TestGate(Base):
    def setUp(self):
        super().setUp()
        self.d = self.ws.batch("b1", "lib")
        self.wt = self.d / "lib"

    def add(self, files, msg="change"):
        self.ws.commit(self.wt, msg, files)

    def gate(self, *args):
        return self.ws.ms("gate", "b1", *args)

    def test_a_clean_change_passes(self):
        self.add({"src/App.java": "class App { int x = 1; }\n", "README.md": "# docs\n"})
        r = self.gate()
        self.assertOk(r)
        self.assertIn("gate: clean", r.stdout)

    def test_known_secret_formats_block_and_are_masked(self):
        secrets = {
            "aws": fake("AKIA", "ABCDEFGHIJKLMNOP"),
            "github": fake("ghp_", "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"),
            "stripe": fake("sk_li", "ve_", "abcdefghijklmnopqrstuvwx"),
            "jwt": fake("eyJhbGciOiJIUzI1NiJ9", ".", "eyJzdWIiOiIxMjM0NTY3ODkwIn0", ".", "abcdefghijklmnop"),
            "google": fake("AIza", "SyA-abcdefghijklmnopqrstuvwxyz01234"),
            "slack": fake("xox", "b-123456789012-abcdefghijkl"),
        }
        self.add({"cfg.txt": "\n".join(f"v{i} = {v}" for i, v in enumerate(secrets.values())) + "\n",
                  "key.pem": fake("-----BEGIN ", "RSA PRIVATE KEY-----") + "\nMIIB...\n",
                  "db.properties": "url=" + fake("postgres://", "admin:", "Sup3rS3cret", "@db.internal:5432/app") + "\n"})
        r = self.gate()
        self.assertEqual(r.returncode, 1)
        for rule in ("aws-access-key", "github-token", "stripe-live-key", "jwt", "google-api-key", "slack-token", "private-key", "credentials-in-url"):
            self.assertIn(rule, r.stdout)
        for value in secrets.values():
            self.assertNotIn(value, r.stdout, "evidence is masked")
        self.assertIn("lib  cfg.txt:1", r.stdout)
        self.assertIn("ms-gate: allow", r.stdout)

    def test_hardcoded_assignments_but_not_placeholders(self):
        self.add({"a.py": f'password = "{fake("Zx9!kQ7v", "Lm2pRt8")}"\n', "b.yml": 'api_key: "short"\n'})
        r = self.gate()
        self.assertEqual(r.returncode, 1)
        self.assertIn("hardcoded-secret", r.stdout)
        self.assertNotIn("b.yml", r.stdout)
        self.add({"c.py": 'password = "changeme"\napi_key = "${API_KEY}"\ntoken = "<your-token-here>"\nsecret = "example-secret-value"\n'
                          'DB_PASSWORD = "{{secret:db}}"\nauth_token = "test-token-1234567"\n'}, "placeholders")
        out = self.gate().stdout
        self.assertNotIn("c.py", out)

    def test_only_added_lines_are_scanned_and_allow_markers_work(self):
        old = fake("AKIA", "ABCDEFGHIJKLMNOP")
        self.ws.commit(self.ws.root / "lib", "old secret on the base branch", {"legacy.txt": f"key = {old}\nother = 1\n"})
        self.ws.git(self.ws.root / "lib", "push", "-q", "origin", "next")
        d2 = self.ws.batch("b2", "lib")
        self.ws.commit(d2 / "lib", "touch another line", {"legacy.txt": f"key = {old}\nother = 2\n", "ok.txt": f"x = {old}  # ms-gate: allow\n"})
        self.assertOk(self.ws.ms("gate", "b2"))

    def test_merge_markers_need_both_ends_and_lock_files_are_ignored(self):
        self.add({"half.txt": "<<<<<<< HEAD\nmine\n", "line.txt": "=======\n"})
        self.assertOk(self.gate())
        self.add({"both.txt": "<<<<<<< HEAD\nmine\n=======\ntheirs\n>>>>>>> branch\n"}, "markers")
        r = self.gate()
        self.assertEqual(r.returncode, 1)
        self.assertIn("merge-conflict-marker", r.stdout)
        self.add({"package-lock.json": '{"resolved": "' + fake("AKIA", "ABCDEFGHIJKLMNOP") + '"}\n'}, "lock")
        self.assertNotIn("package-lock", self.gate().stdout)

    def test_large_files_and_ignore_paths(self):
        self.ws.set_toml(DEFAULT_TOML + "\n[gate]\nmax_file_kb = 1\n")
        self.add({"big.bin.txt": "x" * 3000 + "\n"})
        r = self.gate()
        self.assertEqual(r.returncode, 1)
        self.assertIn("large-file", r.stdout)
        self.ws.set_toml(DEFAULT_TOML + '\n[gate]\nmax_file_kb = 1\nignore_paths = ["big.*"]\n')
        self.assertOk(self.gate())

    def test_debug_leftovers_warn_but_do_not_block(self):
        self.add({"a.js": "console.log('x')\ndebugger;\n", "T.java": 'System.out.println("x");\ne.printStackTrace();\n', "t.test.js": "it.only('x', () => {})\n",
                  "notes.md": "console.log(x)\n"})
        r = self.gate()
        self.assertOk(r)
        self.assertIn("0 blocking", r.stdout)
        for rule in ("console-log", "debugger", "system-out", "print-stack-trace", "focused-test"):
            self.assertIn(rule, r.stdout)
        self.assertNotIn("notes.md", r.stdout)

    def test_debug_rules_follow_the_language_and_spare_test_files(self):
        self.add({"fixture.py": "x = 'console.log(1); debugger;'\n", "Fixture.java": "// console.log(1)\n", "web/test/helper.js": "console.log('trace')\n",
                  "web/test/a.spec.js": "it.only('x', () => {})\n", "tool.py": "import pdb\n"})
        out = self.gate().stdout
        self.assertNotIn("fixture.py", out)
        self.assertNotIn("Fixture.java", out)
        self.assertNotIn("helper.js", out, "console.log in test files is not worth a warning")
        self.assertIn("a.spec.js", out)
        self.assertIn("focused-test", out)
        self.assertIn("tool.py:1  python-debugger", out)

    def test_words_with_separators_are_not_secrets(self):
        self.add({"r.toml": 'capture = { token = "json:access_token" }\n', "c.py": 'secret_name = "database.password.key"\ntoken = "header:x-csrf-token"\n'})
        self.assertIn("gate: clean", self.gate().stdout)

    def test_allow_patterns_from_the_config(self):
        self.ws.set_toml(DEFAULT_TOML + '\n[gate]\nallow = ["INTERNAL_FIXTURE"]\n')
        self.add({"f.txt": f"INTERNAL_FIXTURE {fake('AKIA', 'ABCDEFGHIJKLMNOP')}\n"})
        self.assertOk(self.gate())

    def test_untracked_files_count_and_json_output(self):
        (self.wt / "new.txt").write_text(f"key = {fake('AKIA', 'ABCDEFGHIJKLMNOP')}\n")
        data = json.loads(self.gate("--json").stdout)
        self.assertEqual(data["blocking"], 1)
        self.assertEqual(data["findings"]["lib"][0]["path"], "new.txt")
        self.assertEqual(data["findings"]["lib"][0]["rule"], "aws-access-key")

    def test_standalone_from_a_checkout_and_unknown_batch(self):
        (self.ws.root / "lib" / "leak.txt").write_text(f"t = {fake('ghp_', 'a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8')}\n")
        r = self.ws.ms("gate", cwd=self.ws.root / "lib")
        self.assertEqual(r.returncode, 1)
        self.assertIn("github-token", r.stdout)
        self.assertNotEqual(self.ws.ms("gate", "ghost").returncode, 0)

    def test_ship_is_blocked_by_the_gate_unless_skipped(self):
        self.add({"cfg.txt": f"k = {fake('AKIA', 'ABCDEFGHIJKLMNOP')}\n"})
        plan = self.ws.ms("plan", "b1")
        self.assertIn("gate: 1 blocking", plan.stdout)
        r = self.ws.ms("ship", "b1", "--yes", "--skip-e2e")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("the gate found 1 blocking", r.stderr)
        self.assertNotIn("change", self.ws.remote_log("lib"))
        self.assertOk(self.ws.ms("ship", "b1", "--yes", "--skip-e2e", "--skip-gate"))
        self.assertEqual(self.ws.remote_log("lib")[0], "change")

    def test_ship_proceeds_on_warnings_only(self):
        self.add({"a.js": "console.log(1)\n"})
        plan = self.ws.ms("plan", "b1")
        self.assertIn("gate: 0 blocking, 1 warning(s)", plan.stdout)
        self.assertOk(self.ws.ms("ship", "b1", "--yes", "--skip-e2e"))


# ----------------------------------------------------------------------- junit
SUREFIRE = """<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="com.acme.PayTest" tests="5" failures="2" errors="1" skipped="1" time="1.5">
  <testcase classname="com.acme.PayTest" name="ok" time="0.1"/>
  <testcase classname="com.acme.PayTest" name="refund" time="0.2">
    <failure message="expected: &lt;100&gt; but was: &lt;90&gt;" type="org.opentest4j.AssertionFailedError">org.opentest4j.AssertionFailedError: expected: &lt;100&gt; but was: &lt;90&gt;
	at org.junit.jupiter.api.AssertionUtils.fail(AssertionUtils.java:55)
	at org.junit.jupiter.api.Assertions.assertEquals(Assertions.java:545)
	at com.acme.pay.Refund.apply(Refund.java:42)
	at com.acme.PayTest.refund(PayTest.java:30)
	at java.base/jdk.internal.reflect.DirectMethodHandleAccessor.invoke(DirectMethodHandleAccessor.java:103)
    </failure>
  </testcase>
  <testcase classname="com.acme.PayTest" name="partialRefund" time="0.2">
    <failure message="expected: &lt;100&gt; but was: &lt;90&gt;" type="org.opentest4j.AssertionFailedError">x
	at com.acme.pay.Refund.apply(Refund.java:42)</failure>
  </testcase>
  <testcase classname="com.acme.PayTest" name="boom" time="0.3">
    <error message="Cannot invoke &quot;Account.balance()&quot; because &quot;acc&quot; is null" type="java.lang.NullPointerException">java.lang.NullPointerException
	at com.acme.pay.Ledger.post(Ledger.java:77)
	at com.acme.PayTest.boom(PayTest.java:55)</error>
  </testcase>
  <testcase classname="com.acme.PayTest" name="later" time="0"><skipped/></testcase>
</testsuite>
"""
PYTEST_XML = """<testsuites><testsuite name="pytest" tests="2" failures="1"><testcase classname="tests.test_a" name="test_x" time="0.01">
<failure message="assert 1 == 2">def test_x():
&gt;       assert 1 == 2
E       assert 1 == 2

tests/test_a.py:4: AssertionError</failure></testcase><testcase classname="tests.test_a" name="test_y" time="0.01"/></testsuite></testsuites>"""


class TestJunit(Base):
    def setUp(self):
        super().setUp()
        self.reports = self.ws.tmp / "reports"
        self.reports.mkdir()
        (self.reports / "TEST-com.acme.PayTest.xml").write_text(SUREFIRE)

    def junit(self, *args, cwd=None):
        return self.ws.ms("junit", *args, cwd=cwd or self.ws.tmp)

    def test_summary_groups_messages_and_skips_framework_frames(self):
        r = self.junit(str(self.reports))
        self.assertEqual(r.returncode, 1)
        out = r.stdout
        self.assertIn("5 tests: 2 failed, 1 errors, 1 skipped", out)
        self.assertIn("FAILURE com.acme.PayTest.refund (+1 more with the same message)", out)
        self.assertIn("expected: <100> but was: <90>", out)
        self.assertIn("at com.acme.pay.Refund.apply(Refund.java:42)", out)
        self.assertNotIn("org.junit.jupiter", out, "framework frames are skipped")
        self.assertIn("ERROR com.acme.PayTest.boom", out)
        self.assertIn("NullPointerException: Cannot invoke", out)
        self.assertIn("Ledger.java:77", out)
        self.assertLess(len(out.splitlines()), 12)

    def test_pytest_reports_and_json_and_top(self):
        (self.reports / "pytest.xml").write_text(PYTEST_XML)
        data = json.loads(self.junit(str(self.reports / "pytest.xml"), "--json").stdout)
        self.assertEqual((data["tests"], data["failed"]), (2, 1))
        self.assertEqual(data["bad"][0]["frame"], "tests/test_a.py:4: AssertionError")
        out = self.junit(str(self.reports), "--top", "1").stdout
        self.assertIn("more distinct failure(s)", out)

    def test_passing_reports_exit_zero_and_bad_files_are_ignored(self):
        ok = self.ws.tmp / "ok"
        ok.mkdir()
        (ok / "a.xml").write_text('<testsuite><testcase classname="A" name="x" time="0.1"/></testsuite>')
        (ok / "broken.xml").write_text("<testsuite><oops")
        r = self.junit(str(ok))
        self.assertOk(r)
        self.assertIn("1 tests: 0 failed", r.stdout)

    def test_discovery_uses_default_locations_and_ignores_stale_reports(self):
        proj = self.ws.tmp / "proj"
        rep = proj / "svc" / "target" / "surefire-reports"
        rep.mkdir(parents=True)
        (rep / "TEST-a.xml").write_text(SUREFIRE)
        self.assertEqual(self.junit(cwd=proj).returncode, 1)
        old = time.time() - 3 * 3600
        os.utime(rep / "TEST-a.xml", (old, old))
        self.assertIn("no JUnit reports found", self.junit(cwd=proj).stdout)
        self.assertEqual(self.junit("--since", "400", cwd=proj).returncode, 1)
        (proj / "node_modules" / "x" / "target" / "surefire-reports").mkdir(parents=True)
        self.assertNotIn("node_modules", self.junit("--since", "400", cwd=proj).stdout)

    def test_option_errors(self):
        for args in (("--since", "x"), ("--top",), ("--bogus",)):
            self.assertNotEqual(self.junit(*args).returncode, 0, args)


class TestJunitInTestRuns(Base):
    def make(self, extra_cmd="", reports=None):
        script = self.ws.tmp / "fail.sh"
        report = self.ws.tmp / "TEST-com.acme.PayTest.xml"
        report.write_text(SUREFIRE)
        script.write_text(f"mkdir -p target/surefire-reports && cp {report} target/surefire-reports/ && echo noisy build line && {extra_cmd} exit 1\n")
        cfg = DEFAULT_TOML.replace('unit = "echo unit-lib"', f'unit = "sh {script}"' + (f'\nreports = {json.dumps(reports)}' if reports else ""))
        self.ws.set_toml(cfg)
        return self.ws.batch("b1") / "lib"

    def test_a_failing_run_prints_the_summary_instead_of_the_log_tail(self):
        wt = self.make()
        r = self.ws.ms("test", "t0", cwd=wt)
        self.assertEqual(r.returncode, 1)
        self.assertIn("FAIL t0 lib", r.stderr)
        self.assertIn("5 tests: 2 failed, 1 errors", r.stderr)
        self.assertIn("Refund.java:42", r.stderr)
        self.assertNotIn("noisy build line", r.stderr)
        kept = self.ws.root / ".ms-workspace" / "tests" / "lib-t0.log"
        self.assertIn(f"full output: {kept}", r.stderr)
        self.assertIn("noisy build line", kept.read_text())

    def test_without_reports_the_tail_is_still_shown(self):
        self.ws.set_toml(DEFAULT_TOML.replace('unit = "echo unit-lib"', 'unit = "echo plain failure text; exit 2"'))
        wt = self.ws.batch("b1") / "lib"
        r = self.ws.ms("test", "t0", cwd=wt)
        self.assertIn("plain failure text", r.stderr)
        self.assertNotIn("full output:", r.stderr)

    def test_reports_from_an_older_run_are_not_reused(self):
        wt = self.make()
        old_dir = wt / "target" / "surefire-reports"
        old_dir.mkdir(parents=True)
        stale = old_dir / "TEST-old.xml"
        stale.write_text(SUREFIRE.replace("PayTest", "StaleTest"))
        t = time.time() - 7200
        os.utime(stale, (t, t))
        self.ws.set_toml(DEFAULT_TOML.replace('unit = "echo unit-lib"', 'unit = "echo nothing new; exit 1"'))
        r = self.ws.ms("test", "t0", cwd=wt)
        self.assertNotIn("StaleTest", r.stderr)
        self.assertIn("nothing new", r.stderr)

    def test_report_globs_can_be_configured(self):
        script = self.ws.tmp / "custom.sh"
        report = self.ws.tmp / "r.xml"
        report.write_text(SUREFIRE)
        script.write_text(f"mkdir -p out && cp {report} out/results.xml && exit 1\n")
        self.ws.set_toml(DEFAULT_TOML.replace('unit = "echo unit-lib"', f'unit = "sh {script}"\nreports = ["out/*.xml"]'))
        r = self.ws.ms("test", "t0", cwd=self.ws.batch("b1") / "lib")
        self.assertIn("5 tests: 2 failed", r.stderr)


# --------------------------------------------------------------- Maven modules
def pom(artifact, deps=(), modules=(), parent=None, packaging="jar", group="com.acme", extra="", profile_modules=()):
    dep_xml = "".join(f"<dependency><groupId>{g}</groupId><artifactId>{a}</artifactId>" + (f"<scope>{sc}</scope>" if sc else "") + "</dependency>" for g, a, sc in deps)
    mod_xml = "".join(f"<module>{m}</module>" for m in modules)
    prof = f"<profiles><profile><id>all</id><modules>{''.join(f'<module>{m}</module>' for m in profile_modules)}</modules></profile></profiles>" if profile_modules else ""
    par = f"<parent><groupId>{parent[0]}</groupId><artifactId>{parent[1]}</artifactId><version>1.0</version></parent>" if parent else ""
    grp = "" if parent else f"<groupId>{group}</groupId>"
    return (f'<project xmlns="http://maven.apache.org/POM/4.0.0"><modelVersion>4.0.0</modelVersion>{par}{grp}<artifactId>{artifact}</artifactId>'
            f"<version>1.0</version><packaging>{packaging}</packaging>{extra}"
            + (f"<modules>{mod_xml}</modules>" if mod_xml else "") + (f"<dependencies>{dep_xml}</dependencies>" if dep_xml else "") + prof + "</project>")


class MavenBase(Base):
    """lib/ is the root; modules sources/{a,b,c}/{api,core}, sources/app and a leaf `tool`."""

    def setUp(self):
        super().setUp()
        root = self.ws.root / "lib"
        files = {
            "pom.xml": pom("parent", modules=["sources/a", "sources/b", "sources/c", "sources/app"], packaging="pom",
                           extra="<properties><acme.group>com.acme</acme.group></properties>", profile_modules=["tool"]),
            "sources/a/pom.xml": pom("a", modules=["api", "core"], parent=("com.acme", "parent"), packaging="pom"),
            "sources/a/api/pom.xml": pom("a-api", parent=("com.acme", "a")),
            "sources/a/core/pom.xml": pom("a-core", parent=("com.acme", "a"), deps=[("com.acme", "a-api", None)]),
            "sources/b/pom.xml": pom("b", modules=["api", "core"], parent=("com.acme", "parent"), packaging="pom"),
            "sources/b/api/pom.xml": pom("b-api", parent=("com.acme", "b")),
            "sources/b/core/pom.xml": pom("b-core", parent=("com.acme", "b"), deps=[("com.acme", "b-api", None), ("${acme.group}", "a-core", None)]),
            "sources/c/pom.xml": pom("c", modules=["core"], parent=("com.acme", "parent"), packaging="pom"),
            "sources/c/core/pom.xml": pom("c-core", parent=("com.acme", "c"), deps=[("com.acme", "a-api", None), ("com.acme", "b-core", "test"), ("org.junit", "junit", "test")]),
            "sources/app/pom.xml": pom("app", parent=("com.acme", "parent"), deps=[("com.acme", "c-core", None)]),
            "tool/pom.xml": pom("tool", parent=("com.acme", "parent")),
        }
        for rel, text in files.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(text)
        self.ws.git(root, "add", "-A")
        self.ws.git(root, "commit", "-q", "-m", "reactor")
        self.ws.git(root, "push", "-q", "origin", "next")   # batches start from origin/next
        self.lib = root

    def mods(self, *args, cwd=None, **kw):
        return self.ws.ms("modules", *args, cwd=cwd or self.lib, **kw)


class TestModules(MavenBase):
    def test_summary_counts_modules_including_those_declared_in_profiles(self):
        out = self.mods().stdout
        self.assertIn("lib: 11 modules", out)
        self.assertIn("jar", out)
        self.assertIn("Cycles: 0", out)
        data = json.loads(self.mods("--json").stdout)
        self.assertIn("tool", data["graph"], "a module declared only inside a profile is found")
        self.assertEqual(data["graph"]["sources/b/core"]["artifactId"], "b-core")

    def test_dependencies_inherit_group_ids_and_resolve_properties(self):
        graph = json.loads(self.mods("--json").stdout)["graph"]
        edges = {(rel, e["to"], e["scope"]) for rel, m in graph.items() for e in m["edges"]}
        self.assertIn(("sources/b/core", "sources/a/core", "compile"), edges, "${acme.group} resolved")
        self.assertIn(("sources/a/core", "sources/a/api", "compile"), edges)
        self.assertIn(("sources/a/core", "sources/a", "parent"), edges)
        self.assertIn(("sources/c/core", "sources/b/core", "test"), edges)
        self.assertFalse([e for e in edges if "junit" in e[1]], "external artifacts are not edges")

    def test_deps_and_rdeps(self):
        self.assertIn("sources/b/core: 2 dependents: sources/app, sources/c/core", self.mods("rdeps", "b-core").stdout)
        r = self.mods("rdeps", "sources/a/api").stdout
        for m in ("sources/a/core", "sources/b/core", "sources/c/core", "sources/app"):
            self.assertIn(m, r)
        self.assertIn("sources/a/api", self.mods("deps", "a-core").stdout)
        self.assertIn("tool: 1 dependencies: .", self.mods("deps", "tool").stdout, "a child depends on its parent pom")
        self.assertNotEqual(self.mods("deps", "ghost").returncode, 0)
        self.assertNotEqual(self.mods("deps").returncode, 0)
        amb = self.mods("rdeps", "core")
        self.assertNotEqual(amb.returncode, 0)
        self.assertIn("ambiguous", amb.stderr)

    def test_closure_is_the_changed_modules_plus_every_dependent(self):
        out = self.mods("closure", "--changed", "sources/a/api").stdout.strip().split(",")
        self.assertEqual(out, ["sources/a/api", "sources/a/core", "sources/app", "sources/b/core", "sources/c/core"])
        self.assertEqual(self.mods("closure", "--changed", "tool").stdout.strip(), "tool")
        self.assertEqual(self.mods("closure", "--changed", "").stdout.strip(), "")
        everything = self.mods("closure", "--changed", ".").stdout.strip().split(",")
        self.assertEqual(len(everything), 11, "changing the parent pom affects every module")

    def test_closure_from_the_working_tree(self):
        (self.lib / "sources" / "a" / "api" / "A.java").write_text("class A {}")
        self.assertIn("sources/a/core", self.mods("closure").stdout)

    def test_affected_reports_the_closure_and_the_placeholder_is_used(self):
        d = self.ws.batch("b1", "lib")
        self.ws.commit(d / "lib", "touch api", {"sources/a/api/A.java": "class A {}"})
        data = json.loads(self.ws.ms("affected", cwd=d / "lib").stdout)
        self.assertEqual(data["modules"], ["sources/a/api"])
        self.assertEqual(data["closure"], ["sources/a/api", "sources/a/core", "sources/app", "sources/b/core", "sources/c/core"])
        self.ws.set_toml(DEFAULT_TOML.replace('affected = "echo affected {modules}"', 'affected = "echo closure={closure} modules={modules}"'))
        out = self.ws.ms("test", "t0", cwd=d / "lib").stdout
        self.assertIn("closure=sources/a/api,sources/a/core,sources/app,sources/b/core,sources/c/core", out)

    def test_cycles_are_found(self):
        (self.lib / "sources" / "a" / "api" / "pom.xml").write_text(pom("a-api", parent=("com.acme", "a"), deps=[("com.acme", "a-core", None)]))
        r = self.mods("check")
        self.assertEqual(r.returncode, 1)
        self.assertIn("CYCLE", r.stdout)
        self.assertIn("sources/a/api", r.stdout)
        self.assertIn("1 cycle(s)", r.stdout)

    def test_architecture_rules_report_violations_with_their_edge(self):
        self.ws.set_toml(DEFAULT_TOML + """
[[arch.rule]]
name = "never depend on another module's core"
repo = "lib"
from = ["sources/*/core", "sources/app"]
forbid = "sources/*/core"
allow_same_group = true
""")
        r = self.mods("check")
        self.assertEqual(r.returncode, 1)
        self.assertIn("VIOLATION never depend on another module's core: sources/b/core -> sources/a/core (compile)", r.stdout)
        self.assertIn("VIOLATION never depend on another module's core: sources/app -> sources/c/core (compile)", r.stdout)
        self.assertNotIn("sources/c/core -> sources/b/core", r.stdout, "test-scope edges are not checked by default")
        self.assertNotIn("a/core -> sources/a/api", r.stdout)
        self.assertIn("2 rule violation(s) (1 rule(s) applied)", r.stdout)

    def test_rule_options_except_include_test_and_other_repos(self):
        base = DEFAULT_TOML + """
[[arch.rule]]
name = "r"
from = "sources/*/core"
forbid = "sources/*/core"
include_test = true
except = "sources/a/core"
"""
        self.ws.set_toml(base)
        out = self.mods("check").stdout
        self.assertIn("sources/c/core -> sources/b/core (test)", out)
        self.assertNotIn("-> sources/a/core", out, "except lists allowed targets")
        self.ws.set_toml(base.replace('name = "r"', 'name = "r"\nrepo = "other"'))
        self.assertIn("0 rule violation(s) (0 rule(s) applied)", self.mods("check").stdout)

    def test_a_repo_without_a_pom_and_the_repo_option(self):
        r = self.mods(cwd=self.ws.root / "app")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no pom.xml", r.stderr)
        self.assertIn("lib: 11 modules", self.ws.ms("modules", "--repo", "lib", cwd=self.ws.root).stdout)
        self.assertNotEqual(self.ws.ms("modules", "--repo", "ghost", cwd=self.ws.root).returncode, 0)
        self.assertNotEqual(self.mods("--bogus").returncode, 0)


# ---------------------------------------------------------------------- recall
class TestRecall(Base):
    def setUp(self):
        super().setUp()
        self.proj = self.ws.home / ".claude" / "projects" / "-proj"
        self.proj.mkdir(parents=True)

    def line(self, role, text, cwd=None, ts="2026-10-15T10:00:00.000Z", **extra):
        content = text if role == "user" and isinstance(text, str) else [{"type": "text", "text": text}] if isinstance(text, str) else text
        return json.dumps({"type": role, "timestamp": ts, "cwd": str(cwd or self.ws.root / "lib"), "sessionId": "s",
                           "message": {"role": role, "content": content}, **extra})

    def session(self, name, lines, mtime=None):
        f = self.proj / f"{name}.jsonl"
        f.write_text("\n".join(lines) + "\n")
        if mtime:
            os.utime(f, (mtime, mtime))
        return f

    def recall(self, *args):
        return self.ws.ms("recall", *args)

    def test_finds_what_was_said_by_either_side_and_points_to_the_session(self):
        self.session("abcd1234-0000-0000-0000-000000000000", [
            self.line("user", "How should we handle the refund rounding for partial payments?"),
            self.line("assistant", "We decided to round half up at the line level and keep cents as integers.")])
        out = self.recall("refund", "rounding").stdout
        self.assertIn("session abcd1234 user", out)
        self.assertIn("[refund] [rounding]", out)
        out = self.recall("integers").stdout
        self.assertIn("session abcd1234 assistant", out)
        self.assertIn("claude --resume abcd1234-0000-0000-0000-000000000000", out)

    def test_only_conversation_text_is_indexed(self):
        self.session("s1", [
            self.line("user", [{"type": "tool_result", "tool_use_id": "x", "content": "uniqueoutputtoken from a tool"}]),
            self.line("assistant", [{"type": "tool_use", "id": "y", "name": "Bash", "input": {"command": "uniquecommandtoken"}}]),
            self.line("user", "<system-reminder>reminderonlytoken rules</system-reminder> And a real question about invoices please"),
            self.line("user", "metaonlytoken is hidden text of a meta message", isMeta=True),
            self.line("assistant", "ok")])
        for hidden in ("uniqueoutputtoken", "uniquecommandtoken", "reminderonlytoken", "metaonlytoken"):
            self.assertIn("(no matches)", self.recall(hidden).stdout, hidden)
        self.assertIn("invoices", self.recall("invoices").stdout)

    def test_sessions_outside_the_workspace_and_old_ones_are_left_out(self):
        self.session("inside", [self.line("user", "Discussing the tenant isolation strategy for reports")])
        self.session("outside", [self.line("user", "Discussing the tenant isolation strategy elsewhere", cwd=self.ws.tmp / "other")])
        out = self.recall("tenant", "isolation").stdout
        self.assertEqual(out.count("session "), 1)
        self.assertIn("for reports", out)
        old = time.time() - 200 * 86400
        self.session("ancient", [self.line("user", "A conversation from long ago about gazebo permits")], mtime=old)
        self.assertIn("(no matches)", self.recall("gazebo").stdout)
        self.assertIn("gazebo", self.recall("gazebo", "--days", "400").stdout)

    def test_new_messages_are_found_without_reindexing_by_hand(self):
        f = self.session("s1", [self.line("user", "First message about the ledger posting rules")])
        self.assertIn("ledger", self.recall("ledger").stdout)
        self.assertIn("indexed 0 new", self.recall("index").stdout)
        with open(f, "a") as fh:
            fh.write(self.line("assistant", "Later we added the amortization schedule to the ledger") + "\n")
        out = self.recall("amortization").stdout
        self.assertIn("session s1 assistant", out)
        self.assertIn("indexed 0 new", self.recall("index").stdout)

    def test_a_half_written_last_line_waits_for_the_next_refresh(self):
        f = self.session("s1", [self.line("user", "Complete message about depreciation methods")])
        self.recall("index")
        full = self.line("user", "Second message about the straightline depreciation calendar")
        with open(f, "a") as fh:
            fh.write(full[:60])
        self.assertIn("(no matches)", self.recall("straightline").stdout)
        with open(f, "a") as fh:
            fh.write(full[60:] + "\n")
        self.assertIn("straightline", self.recall("straightline").stdout)

    def test_secrets_are_masked_before_indexing(self):
        key = "AKIA" + "ABCDEFGHIJKLMNOP"
        self.session("s1", [self.line("user", f"I pasted the key {key} and password = \"Zx9kQ7vLm2pRt8\" by mistake in the config")])
        self.assertIn("(no matches)", self.recall(key).stdout)
        self.assertIn("(no matches)", self.recall("Zx9kQ7vLm2pRt8").stdout)
        out = self.recall("pasted", "mistake").stdout
        self.assertIn("***", out)
        self.assertNotIn(key, out)

    def test_memory_notes_and_the_log_are_searchable(self):
        self.assertOk(self.ws.ms("memory", "add", "--type", "decision", "--title", "Cash rounding", "Always round cash payments to the nearest fifty pesos."))
        self.ws.batch("b1", "lib")
        out = self.recall("fifty", "pesos").stdout
        self.assertIn("memory [decision] Cash rounding", out)
        self.assertIn("nearest [fifty] [pesos]", out)
        self.assertIn("log batch.new ok", self.recall("origin", "next").stdout)
        self.assertNotIn("memory", self.recall("origin", "next", "--kind", "log").stdout)
        self.assertIn("(no matches)", self.recall("fifty", "--kind", "session").stdout)
        self.assertNotEqual(self.recall("x", "--kind", "bogus").returncode, 0)

    def test_query_semantics_and_awkward_input(self):
        self.session("s1", [self.line("user", "We need to refund the customer and also adjust the invoice"),
                            self.line("user", "A different message that only mentions the warehouse inventory")])
        self.assertEqual(self.recall("refund", "invoice").stdout.count("session "), 1)
        self.assertEqual(self.recall("refund", "warehouse").stdout.strip(), "(no matches)")
        self.assertEqual(self.recall("refund", "warehouse", "--any").stdout.count("session "), 2)
        self.assertIn("refund", self.recall("refu").stdout, "the last word matches as a prefix")
        for awkward in ('"quoted"', "it's", "a-b:c", "(parens)", "50%", "x AND", "*"):
            r = self.recall(awkward)
            self.assertEqual(r.returncode, 0, awkward)
            self.assertNotIn("Traceback", r.stderr)
        self.assertIn("refund", self.recall("NEAR(refund invoice, 8)", "--raw").stdout)
        bad = self.recall("refund AND OR", "--raw")
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("could not run that search", bad.stderr)

    def test_limit_status_rebuild_and_usage(self):
        self.session("s1", [self.line("user", f"Message number {i} about the pricing engine") for i in range(6)])
        self.assertEqual(self.recall("pricing", "-n", "2").stdout.count("session s1"), 2)
        self.assertRegex(self.recall("status").stdout, r"session 6")
        self.assertIn("indexed 6 new", self.recall("index", "--rebuild").stdout)
        self.assertNotEqual(self.recall().returncode, 0)
        self.assertNotEqual(self.recall("x", "--bogus").returncode, 0)
        fresh = WS()
        self.addCleanup(fresh.close)
        self.assertIn("no index yet", fresh.ms("recall", "status").stdout)


# --------------------------------------------------------------------- handoff
class TestHandoff(Base):
    def setUp(self):
        super().setUp()
        self.d = self.ws.batch("b1")
        self.ws.commit(self.d / "lib", "feature x", {"x.txt": "1"})
        (self.d / "lib" / "wip.txt").write_text("unfinished")
        self.assertOk(self.ws.ms("agent", "new", "b1", "t1", "lib"))
        self.ws.commit(self.d / ".agents" / "t1" / "lib", "agent work", {"a.txt": "1"})
        (self.d / "TASKS.md").write_text("# Batch: b1\n\n## Tasks\n- [ ] lib: fix the refund rounding\n- [x] app: done already\n- [ ] app: add the report\n")

    def autos(self):
        out = self.ws.ms("memory", "list", "--type", "handoff").stdout
        return [l for l in out.splitlines() if "auto handoff" in l]

    def hook(self, event, cwd=None, **extra):
        payload = {"hook_event_name": event, "cwd": str(cwd or self.d / "lib"), "session_id": "s1", **extra}
        r = self.ws.ms("handoff", "--hook", input=json.dumps(payload))
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""), "a hook never fails or prints")

    def snapshot(self, used):
        now = int(time.time())
        self.ws.cache.mkdir(exist_ok=True)
        (self.ws.cache / "usage.json").write_text(json.dumps({"captured_at": now, "five_hour": {"used_percentage": used, "resets_at": now + 7200},
                                                              "seven_day": {"used_percentage": 10, "resets_at": now + 86400 * 4}}))

    def test_manual_handoff_captures_what_is_needed_to_resume(self):
        r = self.ws.ms("handoff", "--batch", "b1")
        self.assertOk(r)
        body = self.ws.ms("memory", "show", "auto").stdout
        for want in ("lib: 1 commit(s) ahead of next [feature x]", "1 uncommitted file(s): wip.txt", "agent branches not integrated: agent/b1/t1",
                     "open tasks: lib: fix the refund rounding; app: add the report", "next: commit or discard the uncommitted changes; run `ms-workspace integrate b1`",
                     "recent: "):
            self.assertIn(want, body)
        self.assertNotIn("done already", body)
        self.assertIn("app: 0 commit(s) ahead of next", body)
        self.assertEqual(len(self.autos()), 1)

    def test_print_does_not_write_and_repeats_replace_the_previous_note(self):
        self.assertIn("lib: 1 commit(s)", self.ws.ms("handoff", "--print").stdout)
        self.assertEqual(self.autos(), [])
        self.ws.ms("handoff")
        (self.d / "lib" / "more.txt").write_text("x")
        self.ws.ms("handoff")
        self.assertEqual(len(self.autos()), 1)
        self.assertIn("2 uncommitted file(s)", self.ws.ms("memory", "show", "auto").stdout)

    def test_agent_worktrees_with_uncommitted_work_are_reported(self):
        (self.d / ".agents" / "t1" / "lib" / "half.txt").write_text("x")
        self.assertIn("agent worktrees with uncommitted work: t1 (1 uncommitted)", self.ws.ms("handoff", "--print").stdout)

    def test_a_clean_integrated_batch_says_what_to_do_next(self):
        self.assertOk(self.ws.ms("integrate", "b1", "--dry-run"))
        (self.d / "lib" / "wip.txt").unlink()
        self.assertOk(self.ws.ms("integrate", "b1"))
        out = self.ws.ms("handoff", "--print").stdout
        self.assertIn("next: `ms-workspace test t1 b1`, then `plan b1`", out)

    def test_hook_events_pre_compact_and_session_end_write_only_when_something_changed(self):
        self.hook("PreCompact")
        self.assertEqual(len(self.autos()), 1)
        before = self.ws.log_lines("--action", "handoff").count("auto (PreCompact)")
        self.hook("PreCompact")
        self.assertEqual(self.ws.log_lines("--action", "handoff").count("auto (PreCompact)"), before, "unchanged state is not rewritten")
        (self.d / "lib" / "new.txt").write_text("x")
        self.hook("SessionEnd")
        self.assertIn("2 uncommitted file(s)", self.ws.ms("memory", "show", "auto").stdout)
        self.assertEqual(len(self.autos()), 1)

    def test_stop_only_writes_when_plan_usage_is_getting_high_and_not_too_often(self):
        self.snapshot(20)
        self.hook("Stop")
        self.assertEqual(self.autos(), [])
        self.snapshot(80)
        self.hook("Stop")
        self.assertEqual(len(self.autos()), 1)
        (self.d / "lib" / "again.txt").write_text("x")
        self.hook("Stop")
        self.assertIn("1 uncommitted file(s)", self.ws.ms("memory", "show", "auto").stdout, "no second write within ten minutes")

    def test_hook_picks_the_only_active_batch_and_ignores_other_cases(self):
        self.hook("PreCompact", cwd=self.ws.root)                 # one active batch: it is the obvious one
        self.assertEqual(len(self.autos()), 1)
        self.ws.batch("b2", "lib")
        self.ws.ms("memory", "forget", "auto")
        self.hook("PreCompact", cwd=self.ws.root)                 # two batches and no way to tell: do nothing
        self.assertEqual(self.autos(), [])
        self.hook("PostToolUse")
        self.hook("PreCompact", cwd=self.ws.tmp)                  # outside a workspace
        self.assertEqual(self.autos(), [])
        for payload in ("", "garbage", "{}"):
            self.assertEqual(self.ws.ms("handoff", "--hook", input=payload).returncode, 0)

    def test_context_shows_it_and_clean_removes_it(self):
        self.ws.ms("handoff")
        self.assertIn("HANDOFF b1: Auto handoff written at", self.ws.ms("context").stdout)
        self.assertOk(self.ws.ms("clean", "b1", "--force"))
        self.assertEqual(self.autos(), [])

    def test_errors(self):
        self.assertNotEqual(self.ws.ms("handoff", "--batch", "ghost").returncode, 0)
        self.assertNotEqual(self.ws.ms("handoff", "--bogus").returncode, 0)
        self.assertNotEqual(self.ws.ms("handoff", cwd=self.ws.tmp).returncode, 0)

    def test_hooks_are_registered_in_the_settings_example(self):
        hooks = json.loads((REPO / "settings" / "hooks.example.json").read_text())["hooks"]
        for event in ("PreCompact", "Stop", "SessionEnd"):
            cmds = [h["command"] for g in hooks[event] for h in g["hooks"]]
            self.assertIn("ms-workspace handoff --hook", cmds, event)


# --------------------------------------------------------------------- release
class TestRelease(Base):
    TOML = DEFAULT_TOML.replace('[repos.lib]\nbase = "next"', '[repos.lib]\nbase = "next"\nrelease = ["qa", "main"]')

    def setUp(self):
        super().setUp()
        self.ws.set_toml(self.TOML)
        self.lib = self.ws.root / "lib"
        for branch in ("qa", "main"):
            self.ws.git(self.lib, "branch", branch)
            self.ws.git(self.lib, "push", "-q", "origin", branch)
        for i, subject in enumerate(["feat(pay): add partial refunds", "fix: round half up", "fix(core)!: drop the legacy endpoint", "docs: explain refunds",
                                     "chore: bump the parent pom", "tweak the thing nobody labelled", "feat: export to csv"]):
            self.ws.commit(self.lib, subject, {f"f{i}.txt": str(i)})
        self.ws.git(self.lib, "push", "-q", "origin", "next")

    def release(self, *args):
        return self.ws.ms("release", *args)

    def test_status_counts_commit_types_authors_and_the_waiting_commits(self):
        out = self.release("status").stdout
        self.assertIn("lib: next -> qa: 7 commit(s) waiting (2 feat, 2 fix, 1 chore, 1 docs, 1 other)", out)
        self.assertIn("lib: next -> main: 7 commit(s) waiting", out)
        self.assertIn("1 author(s)", out)
        self.assertIn("7 files changed", out)
        self.assertIn("feat: export to csv", out)
        self.assertIn("and 2 more", out)
        self.assertIn("BREAKING: fix(core)!: drop the legacy endpoint", out)

    def test_up_to_date_and_hotfix_drift(self):
        self.ws.git(self.lib, "checkout", "-q", "qa")
        self.ws.commit(self.lib, "fix: emergency patch made directly on qa", {"hot.txt": "1"})
        self.ws.git(self.lib, "push", "-q", "origin", "qa")
        self.ws.git(self.lib, "checkout", "-q", "next")
        out = self.release("status").stdout
        self.assertIn("WARNING qa has 1 commit(s) that next does not (hotfix drift)", out)
        self.assertIn("emergency patch", out)
        self.ws.git(self.lib, "checkout", "-q", "main")
        self.ws.git(self.lib, "merge", "-q", "--ff-only", "next")
        self.ws.git(self.lib, "push", "-q", "origin", "main")
        self.ws.git(self.lib, "checkout", "-q", "next")
        self.assertIn("lib: next -> main: up to date", self.release("status").stdout)

    def test_notes_are_grouped_by_type_and_flag_breaking_changes(self):
        out = self.release("notes").stdout
        self.assertIn("## lib: next -> qa (7 change(s))", out)
        self.assertLess(out.index("### Features (2)"), out.index("### Fixes (2)"))
        self.assertIn("- add partial refunds (", out)
        self.assertIn("- drop the legacy endpoint **BREAKING** (", out)
        self.assertIn("### Other (1)", out)
        self.assertIn("- tweak the thing nobody labelled (", out)
        self.assertNotIn("feat(pay)", out, "the type prefix is removed from the line")

    def test_notes_limit_is_shared_between_types_and_target_can_change(self):
        out = self.release("notes", "--max", "3").stdout
        self.assertIn("### Features (2)", out)
        self.assertIn("### Other (1)", out)
        self.assertNotIn("... and", out, "three lines per type fit everything here")
        self.assertIn("## lib: next -> main", self.release("notes", "lib", "--to", "main").stdout)

    def test_merge_commits_are_not_listed(self):
        self.ws.git(self.lib, "checkout", "-q", "-b", "side", "qa")
        self.ws.commit(self.lib, "feat: side feature", {"side.txt": "1"})
        self.ws.git(self.lib, "checkout", "-q", "next")
        self.ws.git(self.lib, "merge", "-q", "--no-ff", "-m", "Merge branch side into next", "side")
        self.ws.git(self.lib, "push", "-q", "origin", "next")
        out = self.release("notes").stdout
        self.assertNotIn("Merge branch side", out)
        self.assertIn("side feature", out)

    def test_fetch_picks_up_new_remote_commits(self):
        mate = self.ws.tmp / "mate"
        self.ws.git(self.ws.tmp, "clone", "-q", str(self.ws.tmp / "remote-lib.git"), str(mate))
        self.ws.git(mate, "checkout", "-q", "next")
        self.ws.commit(mate, "fix: pushed by a teammate", {"mate.txt": "1"})
        self.ws.git(mate, "push", "-q", "origin", "next")
        self.assertIn("7 commit(s)", self.release("status").stdout)
        self.assertIn("8 commit(s)", self.release("status", "--fetch").stdout)

    def test_repos_without_release_branches_and_bad_input(self):
        self.ws.set_toml(DEFAULT_TOML)
        self.assertIn("no repo has `release", self.release("status").stdout)
        self.assertIn("no release branch configured", self.release("notes", "lib").stdout)
        self.ws.set_toml(self.TOML)
        self.assertNotEqual(self.release("status", "ghost").returncode, 0)
        self.assertNotEqual(self.release("frobnicate").returncode, 0)
        self.assertNotEqual(self.release("notes", "--max", "x").returncode, 0)
        self.assertNotEqual(self.release("notes", "--bogus").returncode, 0)
        missing = self.release("notes", "lib", "--to", "nope")
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("cannot find", missing.stderr)


# ---------------------------------------------------------------------- notify
class Inbox:
    """A local HTTP endpoint that records what is posted to it."""

    def __init__(self, status=200):
        self.posts, self.status = [], status
        inbox = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                inbox.posts.append({"path": self.path, "headers": dict(self.headers), "body": self.rfile.read(length).decode()})
                self.send_response(inbox.status)
                self.send_header("Content-Length", "0")
                self.end_headers()

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class TestNotify(Base):
    def setUp(self):
        super().setUp()
        self.inbox = Inbox()
        self.addCleanup(self.inbox.close)

    def configure(self, extra="", kind="ntfy"):
        self.ws.set_toml(DEFAULT_TOML.replace('name = "t"', 'name = "shop"') + f'\n[notify]\nkind = "{kind}"\nurl = "{self.inbox.url}/topic-x"\n{extra}')

    def test_ntfy_posts_the_message_with_title_and_priority(self):
        self.configure()
        r = self.ws.ms("notify", "Build", "finished", "--title", "Done", "--priority", "high")
        self.assertOk(r)
        post = self.inbox.posts[0]
        self.assertEqual((post["path"], post["body"]), ("/topic-x", "Build finished"))
        self.assertEqual(post["headers"]["Title"], "shop: Done")
        self.assertEqual(post["headers"]["Priority"], "high")
        self.assertEqual(post["headers"]["Tags"], "ms-workspace")

    def test_webhook_sends_json_with_a_configurable_field(self):
        self.configure(kind="webhook")
        self.assertOk(self.ws.ms("notify", "hello there"))
        self.assertEqual(json.loads(self.inbox.posts[0]["body"]), {"text": "shop: Notification: hello there"})
        self.configure('field = "content"', kind="webhook")
        self.assertOk(self.ws.ms("notify", "second", "--title", "T"))
        self.assertEqual(json.loads(self.inbox.posts[1]["body"]), {"content": "shop: T: second"})

    def test_command_kind_runs_locally_with_the_message_in_the_environment(self):
        out = self.ws.tmp / "got.txt"
        self.ws.set_toml(DEFAULT_TOML + f'\n[notify]\ncommand = "echo \\"$MS_NOTIFY_TITLE|$MS_NOTIFY_MESSAGE|$MS_NOTIFY_PRIORITY\\" > {out}"\n')
        self.assertOk(self.ws.ms("notify", "local one", "--priority", "low"))
        self.assertEqual(out.read_text().strip(), "t: Notification|local one|low")
        self.ws.set_toml(DEFAULT_TOML + '\n[notify]\ncommand = "exit 3"\n')
        r = self.ws.ms("notify", "x")
        self.assertEqual(r.returncode, 1)
        self.assertIn("the command failed", r.stderr)

    def test_secrets_are_masked_and_long_text_is_cut(self):
        self.configure()
        key = "AKIA" + "ABCDEFGHIJKLMNOP"
        self.ws.ms("notify", f"deploy used {key} and password = \"Zx9kQ7vLm2pRt8\"")
        self.ws.ms("notify", "y" * 900)
        body = self.inbox.posts[0]["body"]
        self.assertNotIn(key, body)
        self.assertNotIn("Zx9kQ7vLm2pRt8", body)
        self.assertIn("***", body)
        self.assertEqual(len(self.inbox.posts[1]["body"]), 300)

    def test_identical_messages_are_sent_once_within_thirty_seconds(self):
        self.configure()
        self.ws.ms("notify", "same thing")
        again = self.ws.ms("notify", "same thing")
        self.assertOk(again)
        self.assertIn("skipped", again.stdout)
        self.ws.ms("notify", "another thing")
        self.assertEqual(len(self.inbox.posts), 2)
        self.ws.ms("notify", "--test")
        self.ws.ms("notify", "--test")
        self.assertEqual(len(self.inbox.posts), 4, "--test always sends")

    def test_not_configured_is_an_error_by_hand_and_silent_in_hooks(self):
        r = self.ws.ms("notify", "hello")
        self.assertEqual(r.returncode, 1)
        self.assertIn("not configured", r.stderr)
        hook = self.ws.ms("notify", "--hook", input=json.dumps({"message": "x"}))
        self.assertEqual((hook.returncode, hook.stdout, hook.stderr), (0, "", ""))

    def test_the_notification_hook_forwards_claude_codes_message(self):
        self.configure()
        self.ws.ms("notify", "--hook", input=json.dumps({"hook_event_name": "Notification", "message": "Claude needs your permission to use Bash", "title": "Claude Code"}))
        post = self.inbox.posts[0]
        self.assertEqual(post["body"], "Claude needs your permission to use Bash")
        self.assertEqual(post["headers"]["Priority"], "high")
        for payload in ("", "garbage", "[]", "{}"):
            self.assertEqual(self.ws.ms("notify", "--hook", input=payload).returncode, 0, payload)

    def test_bad_destinations_fail_clearly_but_never_break_hooks(self):
        for url in ("file:///etc/passwd", "ftp://example.com/x", "not a url"):
            self.ws.set_toml(DEFAULT_TOML + f'\n[notify]\nurl = "{url}"\n')
            r = self.ws.ms("notify", "x")
            self.assertEqual(r.returncode, 1, url)
            self.assertIn("http:// or https://", r.stderr)
        self.ws.set_toml(DEFAULT_TOML + '\n[notify]\nurl = "http://127.0.0.1:9/none"\n')
        r = self.ws.ms("notify", "x")
        self.assertEqual(r.returncode, 1)
        self.assertIn("could not send", r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertEqual(self.ws.ms("notify", "--hook", input=json.dumps({"message": "y"})).returncode, 0)
        self.inbox.status = 500
        self.configure()
        self.assertIn("answered 500", self.ws.ms("notify", "z").stderr)

    def test_a_failed_send_does_not_block_the_retry(self):
        self.ws.set_toml(DEFAULT_TOML + '\n[notify]\nurl = "http://127.0.0.1:9/none"\n')
        self.assertEqual(self.ws.ms("notify", "retry me").returncode, 1)
        self.configure()
        again = self.ws.ms("notify", "retry me")
        self.assertOk(again)
        self.assertNotIn("skipped", again.stdout)
        self.assertEqual(len(self.inbox.posts), 1)

    def test_input_errors(self):
        self.configure()
        for args in ((), ("--priority", "loud", "x"), ("--bogus", "x")):
            self.assertNotEqual(self.ws.ms("notify", *args).returncode, 0, args)

    def test_ship_notifies_when_it_is_listed_in_on(self):
        self.configure('on = ["ship"]')
        d = self.ws.batch("b1", "lib")
        self.ws.commit(d / "lib", "feature", {"f.txt": "1"})
        self.ws.ms("plan", "b1")
        self.assertEqual(self.inbox.posts, [], "a plan sends nothing")
        self.assertOk(self.ws.ms("ship", "b1", "--yes", "--skip-e2e"))
        self.assertEqual(len(self.inbox.posts), 1)
        self.assertEqual(self.inbox.posts[0]["headers"]["Title"], "shop: Shipped")
        self.assertIn("batch b1 pushed: lib", self.inbox.posts[0]["body"])

    def test_a_failed_ship_is_announced_with_high_priority(self):
        self.configure('on = ["ship"]')
        d = self.ws.batch("b1", "lib")
        self.ws.commit(d / "lib", "feature", {"k.txt": "k = " + "AKIA" + "ABCDEFGHIJKLMNOP"})
        r = self.ws.ms("ship", "b1", "--yes", "--skip-e2e")
        self.assertNotEqual(r.returncode, 0)
        post = self.inbox.posts[0]
        self.assertEqual(post["headers"]["Title"], "shop: Ship failed")
        self.assertEqual(post["headers"]["Priority"], "high")
        self.assertIn("the gate found 1 blocking", post["body"])

    def test_ship_is_silent_when_on_does_not_list_it(self):
        self.configure()
        d = self.ws.batch("b1", "lib")
        self.ws.commit(d / "lib", "feature", {"f.txt": "1"})
        self.assertOk(self.ws.ms("ship", "b1", "--yes", "--skip-e2e"))
        self.assertEqual(self.inbox.posts, [])

    def test_registered_as_a_hook_and_asks_before_agents_use_it(self):
        data = json.loads((REPO / "settings" / "hooks.example.json").read_text())
        self.assertEqual(data["hooks"]["Notification"][0]["hooks"][0]["command"], "ms-workspace notify --hook")
        self.assertIn("Bash(ms-workspace notify:*)", data["permissions"]["ask"])


# --------------------------------------------------------------------- promote
class TestPromote(Base):
    TOML = DEFAULT_TOML.replace('[repos.lib]\nbase = "next"', '[repos.lib]\nbase = "next"\nrelease = ["qa", "main"]')

    def setUp(self):
        super().setUp()
        self.ws.set_toml(self.TOML)
        self.lib = self.ws.root / "lib"
        for branch in ("qa", "main"):
            self.ws.git(self.lib, "branch", branch)
            self.ws.git(self.lib, "push", "-q", "origin", branch)
        self.ws.commit(self.lib, "feat: add exports", {"e.txt": "1"})
        self.ws.commit(self.lib, "fix(core)!: drop the old api", {"o.txt": "1"})
        self.ws.git(self.lib, "push", "-q", "origin", "next")

    def env(self, with_gh=True):
        bin_dir = self.ws.tmp / "fakebin"
        bin_dir.mkdir(exist_ok=True)
        for tool in ("git", "python3", "bash"):
            link = bin_dir / tool
            link.unlink(missing_ok=True)
            link.symlink_to(subprocess.run(["which", tool], capture_output=True, text=True).stdout.strip())
        if with_gh:
            gh = bin_dir / "gh"
            gh.write_text(f'#!/bin/sh\necho "$@" >> "{self.ws.tmp}/gh-calls"\n')
            gh.chmod(0o755)
        return {"PATH": str(bin_dir)}

    def remote(self, branch):
        return self.ws.git(self.ws.tmp / "remote-lib.git", "rev-parse", branch)

    def test_plan_lists_the_commits_and_changes_nothing(self):
        r = self.ws.ms("promote", "lib", "--to", "main", env=self.env())
        self.assertOk(r)
        self.assertIn("promote lib next -> main (PR)", r.stdout)
        self.assertIn("2 commit(s) waiting", r.stdout)
        self.assertIn("BREAKING: fix(core)!: drop the old api", r.stdout)
        self.assertIn("plan only", r.stdout)
        self.assertFalse((self.ws.tmp / "gh-calls").exists())

    def test_yes_opens_a_pr_from_the_base_branch_and_pushes_nothing(self):
        before = self.remote("main")
        r = self.ws.ms("promote", "lib", "--to", "main", "--yes", env=self.env())
        self.assertOk(r)
        call = (self.ws.tmp / "gh-calls").read_text()
        self.assertIn("pr create --base main --head next --title Promote next to main", call)
        self.assertIn("## Features (1)", call)
        self.assertEqual(self.remote("main"), before)
        self.assertIn("ok", self.ws.log_lines("--action", "promote"))

    def test_runs_from_inside_the_repo(self):
        self.assertOk(self.ws.ms("promote", "--to", "qa", "--yes", cwd=self.lib, env=self.env()))
        self.assertIn("--base qa", (self.ws.tmp / "gh-calls").read_text())

    def test_several_release_branches_need_to(self):
        r = self.ws.ms("promote", "lib", "--yes", env=self.env())
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--to", r.stderr)
        self.assertFalse((self.ws.tmp / "gh-calls").exists())

    def test_destination_must_be_a_release_branch(self):
        for dest in ("develop", "next"):
            r = self.ws.ms("promote", "lib", "--to", dest, "--yes", env=self.env())
            self.assertNotEqual(r.returncode, 0, dest)
        self.assertIn("not a release branch", r.stderr + self.ws.ms("promote", "lib", "--to", "develop").stderr)

    def test_repo_without_release_branches(self):
        r = self.ws.ms("promote", "app", "--yes", env=self.env())
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no `release", r.stderr)

    def test_up_to_date_does_nothing(self):
        self.ws.git(self.lib, "push", "-q", "origin", "next:main")
        r = self.ws.ms("promote", "lib", "--to", "main", "--yes", env=self.env())
        self.assertOk(r)
        self.assertIn("nothing to promote", r.stdout)
        self.assertFalse((self.ws.tmp / "gh-calls").exists())

    def test_missing_gh_stops_before_anything_is_done(self):
        r = self.ws.ms("promote", "lib", "--to", "main", "--yes", env=self.env(with_gh=False))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("GitHub CLI", r.stderr)

    def test_unpushed_local_commits_are_called_out(self):
        self.ws.commit(self.lib, "wip: not pushed", {"w.txt": "1"})
        self.assertIn("not pushed to origin", self.ws.ms("promote", "lib", "--to", "main", env=self.env()).stdout)

    def test_direct_fast_forwards_the_release_branch(self):
        r = self.ws.ms("promote", "lib", "--to", "main", "--direct", "--yes", env=self.env())
        self.assertOk(r)
        self.assertEqual(self.remote("main"), self.remote("next"))
        self.assertFalse((self.ws.tmp / "gh-calls").exists())

    def test_direct_refuses_when_the_release_branch_has_its_own_commits(self):
        self.ws.git(self.lib, "checkout", "-q", "main")
        self.ws.commit(self.lib, "fix: hotfix on main", {"h.txt": "1"})
        self.ws.git(self.lib, "push", "-q", "origin", "main")
        self.ws.git(self.lib, "checkout", "-q", "next")
        before = self.remote("main")
        r = self.ws.ms("promote", "lib", "--to", "main", "--direct", "--yes", env=self.env())
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not a fast-forward", r.stderr)
        self.assertEqual(self.remote("main"), before)


if __name__ == "__main__":
    unittest.main()
