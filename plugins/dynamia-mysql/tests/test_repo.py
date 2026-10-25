import json
import os
import re
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
SKILLS = os.path.join(ROOT, "skills")


class RepoTest(unittest.TestCase):
    def test_skill_front_matter(self):
        names = sorted(os.listdir(SKILLS))
        self.assertEqual(len(names), 5)
        for name in names:
            with open(os.path.join(SKILLS, name, "SKILL.md"), encoding="utf-8") as fh:
                text = fh.read()
            m = re.match(r"---\nname: (.+)\ndescription: (.+)\n---\n", text)
            self.assertIsNotNone(m, name)
            self.assertEqual(m.group(1), name)
            self.assertNotIn(": ", m.group(2), name)

    def test_hook_points_to_an_executable_script(self):
        with open(os.path.join(ROOT, "hooks", "hooks.json")) as fh:
            cmd = json.load(fh)["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        script = cmd.replace('"${CLAUDE_PLUGIN_ROOT}/', "").rstrip('"')
        self.assertTrue(os.access(os.path.join(ROOT, script), os.X_OK))

    def test_skills_reference_existing_tool_commands(self):
        with open(os.path.join(ROOT, "bin", "mysql-tool")) as fh:
            tool = fh.read()
        for name in os.listdir(SKILLS):
            with open(os.path.join(SKILLS, name, "SKILL.md"), encoding="utf-8") as fh:
                text = fh.read()
            for sub in re.findall(r"mysql-tool (?:\S+ )?(secret-set|secret-gen|info|inspect|replica-status|plan-replica|query|exec|profiles|secrets)\b", text):
                self.assertIn('"%s"' % sub, tool, sub)

    def test_no_literal_passwords_in_docs(self):
        for base, _, files in os.walk(SKILLS):
            for f in files:
                with open(os.path.join(base, f), encoding="utf-8") as fh:
                    self.assertIsNone(re.search(r"(?i)password\s*=\s*'(?!@@ENV:|\*)[^']+'", fh.read()), f)


if __name__ == "__main__":
    unittest.main()
