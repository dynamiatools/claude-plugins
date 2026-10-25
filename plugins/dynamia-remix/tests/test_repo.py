import json
import os
import re
import subprocess
import sys
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
SKILLS = os.path.join(ROOT, "skills")


class RepoTest(unittest.TestCase):
    def test_skill_front_matter(self):
        names = sorted(os.listdir(SKILLS))
        self.assertEqual(len(names), 6)
        for name in names:
            text = open(os.path.join(SKILLS, name, "SKILL.md"), encoding="utf-8").read()
            m = re.match(r"---\nname: (.+)\ndescription: (.+)\n---\n", text)
            self.assertIsNotNone(m, name)
            self.assertEqual(m.group(1), name)
            self.assertNotIn(": ", m.group(2), name)

    def test_manifest(self):
        m = json.load(open(os.path.join(ROOT, ".claude-plugin", "plugin.json")))
        self.assertEqual(m["name"], "dynamia-remix")

    def test_scripts_referenced_by_skills_exist(self):
        for name in os.listdir(SKILLS):
            text = open(os.path.join(SKILLS, name, "SKILL.md"), encoding="utf-8").read()
            for script in re.findall(r"\$\{CLAUDE_PLUGIN_ROOT\}/bin/([\w-]+)", text):
                self.assertTrue(os.access(os.path.join(ROOT, "bin", script), os.X_OK), script)

    def test_template_matrix_scores(self):
        out = subprocess.run([sys.executable, os.path.join(ROOT, "bin", "remix-parity"),
                              os.path.join(SKILLS, "recon", "features.csv")], capture_output=True, text=True)
        self.assertEqual(out.returncode, 1)
        self.assertIn("Parity 0%", out.stdout)


if __name__ == "__main__":
    unittest.main()
