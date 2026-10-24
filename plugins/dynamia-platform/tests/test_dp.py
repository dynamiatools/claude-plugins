import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BIN = ROOT / "bin"

FULL_BOTH = ("dynamia new --name shop --scaffold both --backend-lang java --group-id com.acme --artifact-id shop "
             "--version 1.0.0 --description x --frontend vue --pm pnpm --yes --no-git")


def run(script, stdin="", *args):
    return subprocess.run([str(BIN / script), *args], input=stdin, capture_output=True, text=True, timeout=20)


def bash_payload(command):
    return json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})


class Detect(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, rel, text=""):
        p = self.d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def test_plain_directory_is_silent(self):
        self.write("pom.xml", "<project><artifactId>x</artifactId></project>")
        r = run("dp-detect", "", str(self.d))
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_missing_directory_is_silent_and_ok(self):
        r = run("dp-detect", "", str(self.d / "nope"))
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_backend_zk_and_version_from_property(self):
        self.write("pom.xml", "<project><properties><dynamiatools.version>26.10.3</dynamiatools.version></properties>"
                              "<dependency><groupId>tools.dynamia</groupId></dependency></project>")
        self.write("src/main/webapp/a.zul", "<window/>")
        out = run("dp-detect", "", str(self.d)).stdout
        self.assertIn("Dynamia Platform 26.10.3: backend + ZK.", out)

    def test_backend_without_zul_is_not_zk(self):
        self.write("pom.xml", "<dependency><groupId>tools.dynamia</groupId></dependency>")
        out = run("dp-detect", "", str(self.d)).stdout
        self.assertIn("backend.", out)
        self.assertNotIn("ZK", out)

    def test_vue_deep_in_monorepo_with_catalog_version(self):
        self.write("a/b/c/d/e/f/package.json", '{"dependencies": {"@dynamia-tools/vue": "catalog:"}}')
        out = run("dp-detect", "", str(self.d)).stdout
        self.assertIn("Vue", out)
        self.assertIn("(version unknown)", out)

    def test_npm_range_gives_version(self):
        self.write("package.json", '{"dependencies": {"@dynamia-tools/sdk": "^26.10.1"}}')
        out = run("dp-detect", "", str(self.d)).stdout
        self.assertIn("Dynamia Platform 26.10.1: TS SDK.", out)

    def test_ignores_node_modules_and_target(self):
        self.write("node_modules/x/package.json", '{"dependencies": {"@dynamia-tools/vue": "1"}}')
        self.write("target/pom.xml", "tools.dynamia")
        self.assertEqual(run("dp-detect", "", str(self.d)).stdout, "")

    def test_facts_for_non_dynamia(self):
        self.assertEqual(run("dp-detect", "", "--facts", str(self.d)).stdout.strip(), "dynamia=no")

    def test_facts_for_dynamia(self):
        self.write("package.json", '{"dependencies": {"@dynamia-tools/vue": "^26.10.0"}}')
        facts = dict(l.split("=", 1) for l in run("dp-detect", "", "--facts", str(self.d)).stdout.splitlines())
        self.assertEqual((facts["dynamia"], facts["vue"], facts["backend"], facts["version"]), ("yes", "yes", "no", "26.10.0"))


class Session(unittest.TestCase):
    def test_prints_inside_dynamia_project_and_stays_silent_elsewhere(self):
        with tempfile.TemporaryDirectory() as t:
            Path(t, "package.json").write_text('{"dependencies": {"@dynamia-tools/vue": "^26.10.0"}}')
            r = run("dp-session", json.dumps({"cwd": t}))
            self.assertIn("Dynamia Platform 26.10.0", r.stdout)
        with tempfile.TemporaryDirectory() as t:
            r = run("dp-session", json.dumps({"cwd": t}))
            self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_bad_input_never_fails(self):
        self.assertEqual(run("dp-session", "not json").returncode, 0)


class Guard(unittest.TestCase):
    def blocked(self, command):
        r = run("dp-guard", bash_payload(command))
        return r.returncode == 2, r.stderr

    def test_unrelated_commands_pass(self):
        for c in ("ls -la", "mvn test", "npm install -g @dynamia-tools/cli", "dynamia --version", "echo newsletter"):
            self.assertEqual(self.blocked(c)[0], False, c)

    def test_bare_wizard_is_blocked_and_explains(self):
        blocked, msg = self.blocked("dynamia new")
        self.assertTrue(blocked)
        self.assertIn("--name", msg)
        self.assertIn("! dynamia new", msg)

    def test_partial_flags_are_blocked(self):
        self.assertTrue(self.blocked("dynamia new --name shop --yes")[0])

    def test_full_flags_pass(self):
        self.assertFalse(self.blocked(FULL_BOTH)[0])

    def test_backend_only_does_not_need_frontend_flags(self):
        cmd = ("dynamia new --name api --scaffold backend --backend-lang kotlin --group-id a.b --artifact-id api "
               "--version 1.0.0 --description '' --yes --git")
        self.assertFalse(self.blocked(cmd)[0])

    def test_frontend_only_does_not_need_backend_flags(self):
        self.assertFalse(self.blocked("dynamia new --name ui --scaffold frontend --frontend vue --pm npm --yes --no-git")[0])

    def test_after_a_wrapper_or_pipe(self):
        self.assertTrue(self.blocked("cd /tmp && dynamia new")[0])
        self.assertTrue(self.blocked("npx dynamia new")[0])

    def test_garbage_input_is_allowed(self):
        r = run("dp-guard", "")
        self.assertEqual(r.returncode, 0)


class Layout(unittest.TestCase):
    def test_hooks_json_points_to_executable_scripts(self):
        hooks = json.loads((ROOT / "hooks" / "hooks.json").read_text())["hooks"]
        for event in hooks.values():
            for entry in event:
                for h in entry["hooks"]:
                    script = h["command"].strip('"').replace("${CLAUDE_PLUGIN_ROOT}", str(ROOT))
                    self.assertTrue(os.access(script, os.X_OK), script)

    def test_skills_have_front_matter(self):
        for skill in (ROOT / "skills").glob("*/SKILL.md"):
            head = skill.read_text().split("---")[1]
            self.assertIn(f"name: {skill.parent.name}", head, skill)
            self.assertIn("description:", head, skill)


if __name__ == "__main__":
    unittest.main()


class CliUpdate(unittest.TestCase):
    """dp-cli-update with a fake `dynamia` and `npm` first on PATH."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = Path(self._tmp.name)
        self.bin = self.d / "bin"
        self.bin.mkdir()
        self.log = self.d / "npm.log"

    def tearDown(self):
        self._tmp.cleanup()

    def fake(self, name, body):
        p = self.bin / name
        p.write_text("#!/bin/sh\n" + body)
        p.chmod(0o755)

    def setup_tools(self, installed, latest, install_ok=True):
        if installed:
            self.fake("dynamia", f'echo "dynamia/{installed} linux-x64"\n')
        self.fake("npm", (
            f'case "$1" in\n'
            f'  view) [ -n "{latest}" ] && echo "{latest}" || exit 1 ;;\n'
            f'  prefix) echo "$HOME/.npm-global" ;;\n'
            f'  install) echo "$@" >> "{self.log}"; {"exit 0" if install_ok else "exit 1"} ;;\n'
            f'esac\n'))

    def run_cli(self, *args):
        env = {"PATH": f"{self.bin}:/usr/bin:/bin", "HOME": os.environ.get("HOME", "/root")}
        return subprocess.run([str(BIN / "dp-cli-update"), *args], capture_output=True, text=True, timeout=20, env=env)

    def test_current(self):
        self.setup_tools("1.2.0", "1.2.0")
        self.assertEqual(self.run_cli().stdout.strip(), "status=current installed=1.2.0 latest=1.2.0")

    def test_outdated_check_does_not_install(self):
        self.setup_tools("1.2.0", "1.10.0")
        r = self.run_cli()
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "status=outdated installed=1.2.0 latest=1.10.0"))
        self.assertFalse(self.log.exists())

    def test_apply_installs_latest_when_outdated(self):
        self.setup_tools("1.2.0", "1.3.0")
        r = self.run_cli("--apply")
        self.assertEqual(r.returncode, 0)
        self.assertIn("install -g @dynamia-tools/cli@latest", self.log.read_text())

    def test_apply_installs_when_missing(self):
        self.setup_tools(None, "1.3.0")
        self.assertIn("status=missing", self.run_cli("--apply").stdout)
        self.assertTrue(self.log.exists())

    def test_apply_does_nothing_when_current_or_newer(self):
        self.setup_tools("2.0.0-beta.1", "1.3.0")
        self.assertEqual(self.run_cli("--apply").returncode, 0)
        self.assertFalse(self.log.exists())

    def test_offline_is_unknown_and_never_installs(self):
        self.setup_tools("1.2.0", "")
        r = self.run_cli("--apply")
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "status=unknown installed=1.2.0 latest=unknown"))
        self.assertFalse(self.log.exists())

    def test_failed_install_exits_1(self):
        self.setup_tools("1.2.0", "1.3.0", install_ok=False)
        self.assertEqual(self.run_cli("--apply").returncode, 1)
