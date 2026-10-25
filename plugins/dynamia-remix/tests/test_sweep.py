import os
import tempfile
import unittest

from _load import load

sweep = load("remix-sweep")


def run(files, avoid=(), domains=(), colors=()):
    with tempfile.TemporaryDirectory() as d:
        for rel, text in files.items():
            p = os.path.join(d, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "w").write(text)
        return sweep.sweep(d, sweep.patterns(avoid, domains, colors))


class SweepTest(unittest.TestCase):
    def test_name_inside_identifiers(self):
        for src in ("OriginalAppEmbed", "original_app", "original-app", "Original App"):
            self.assertEqual(len(run({"a.ts": "const x = %s;" % src}, avoid=["Original App"])), 1, src)

    def test_clean_code(self):
        self.assertEqual(run({"a.ts": "const booking = 1;"}, avoid=["Original App"]), [])

    def test_domain(self):
        self.assertEqual(len(run({"a.html": '<a href="https://Original.com/x">'}, domains=["original.com"])), 1)

    def test_colors_short_and_long_forms(self):
        self.assertEqual(len(run({"a.css": "a{color:#06F}"}, colors=["#0066ff"])), 1)
        self.assertEqual(len(run({"a.css": "a{color:#0066FF}"}, colors=["#06f"])), 1)
        self.assertEqual(run({"a.css": "a{color:#0066ffaa}"}, colors=["#0066ff"]), [])

    def test_skips_remix_folder_and_node_modules(self):
        files = {"remix/recon.md": "Original App", "node_modules/x/a.js": "Original App"}
        self.assertEqual(run(files, avoid=["Original App"]), [])

    def test_filename_hit(self):
        self.assertEqual(len(run({"OriginalApp.tsx": "x"}, avoid=["Original App"])), 1)

    def test_nothing_to_look_for_is_an_error(self):
        self.assertEqual(sweep.main(["."]), 2)


if __name__ == "__main__":
    unittest.main()
