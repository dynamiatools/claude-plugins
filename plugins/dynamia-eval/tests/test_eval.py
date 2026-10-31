import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SCRIPT = ROOT / "bin" / "eval.py"
sys.path.insert(0, str(ROOT / "bin"))

import eval as ev  # noqa: E402


def noul(**kw):
    return {"id": "r", "type": "noul", "instructions": "q?", **kw}


class Validate(unittest.TestCase):
    def test_valid_examples_ship_clean(self):
        rules, errors = ev.load_rules(ROOT / "examples" / "rules")
        self.assertEqual(errors, [])
        self.assertEqual(len(rules), 5)

    def test_problems(self):
        cases = [
            ({"id": "Bad Id", "type": "noul", "instructions": "q"}, "id must be"),
            ({"id": "a", "type": "nope"}, "type must be"),
            ({"id": "a", "type": "noul"}, "needs instructions"),
            ({"id": "a", "type": "noul", "instructions": "q", "zzz": 1}, "unknown key"),
            ({"id": "a", "type": "noul", "instructions": "q", "pass": {"min": 2}}, "0..1"),
            ({"id": "a", "type": "noul", "check": {"regex": "x"}}, "expect must be"),
            ({"id": "a", "type": "noul", "check": {"regex": "(", "expect": "absent"}}, "bad regex"),
            ({"id": "a", "type": "noul", "check": {"max_chars": 5}, "pass": {"min": 0.5}}, "pass is ignored"),
            ({"id": "a", "type": "choice", "instructions": "q", "options": ["x", "y"]}, "pass.accept"),
            ({"id": "a", "type": "choice", "instructions": "q", "options": ["x", "y"], "pass": {"accept": ["z"]}}, "pass.accept"),
            ({"id": "a", "type": "score", "instructions": "q", "levels": ["a", "b"]}, "pass.min or pass.max"),
            ({"id": "a", "type": "score", "instructions": "q", "levels": ["a", "b"], "pass": {"min": 3}}, "1..2"),
            ({"id": "a", "type": "noul", "instructions": "q", "severity": "x"}, "severity"),
            ({"id": "a", "type": "noul", "instructions": "q", "example": [{"state": "s", "expect": "maybe"}]}, "example 0"),
            ({"id": "a", "type": "choice", "instructions": "q", "options": ["x", "y"], "pass": {"accept": ["x"]},
              "check": {"max_chars": 1}}, "only allowed on noul"),
        ]
        for rule, needle in cases:
            with self.subTest(needle=needle):
                self.assertTrue(any(needle in e for e in ev.validate_rule(rule)), ev.validate_rule(rule))

    def test_duplicate_ids_and_bad_toml(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "a.toml").write_text('[[rule]]\nid="x"\ntype="noul"\ninstructions="q"\n')
            (Path(d) / "b.toml").write_text('[[rule]]\nid="x"\ntype="noul"\ninstructions="q"\n')
            (Path(d) / "c.toml").write_text("not = [toml")
            rules, errors = ev.load_rules(d)
            self.assertEqual(len(rules), 1)
            self.assertTrue(any("duplicate id" in e for e in errors))
            self.assertTrue(any(e.startswith("c.toml") for e in errors))

    def test_missing_path(self):
        self.assertTrue(ev.load_rules("/nonexistent-dir-xyz")[1])


class Check(unittest.TestCase):
    def test_regex_and_lengths(self):
        r = noul(check={"regex": "secret", "expect": "absent", "ignore_case": True})
        self.assertEqual(ev.run_check(r, "all fine")[0], "pass")
        self.assertEqual(ev.run_check(r, "my SECRET")[0], "fail")
        r = noul(check={"regex": "ok", "expect": "present"})
        self.assertEqual(ev.run_check(r, "nothing")[0], "fail")
        r = noul(check={"min_chars": 3, "max_chars": 5})
        self.assertEqual([ev.run_check(r, s)[0] for s in ("ab", "abcd", "abcdef")], ["fail", "pass", "fail"])


class Judge(unittest.TestCase):
    def test_noul_default_and_bounds(self):
        r = noul()
        self.assertEqual(ev.judge(r, {"noul": 0.5})[0], "pass")
        self.assertEqual(ev.judge(r, {"noul": 0.49})[0], "fail")
        self.assertEqual(ev.judge(r, {"noul": True})[0], "pass")
        self.assertEqual(ev.judge(r, {"noul": 1.5})[0], "error")
        self.assertEqual(ev.judge(r, {"noul": "yes"})[0], "error")
        self.assertEqual(ev.judge(r, "yes")[0], "error")
        r = noul(**{"pass": {"max": 0.2}})
        self.assertEqual(ev.judge(r, {"noul": 0.1})[0], "pass")
        self.assertEqual(ev.judge(r, {"noul": 0.3})[0], "fail")

    def test_choice(self):
        r = {"id": "c", "type": "choice", "options": ["a", "b", "c"], "pass": {"accept": ["a", "b"], "min_confidence": 0.6}}
        self.assertEqual(ev.judge(r, {"choice": "a", "confidence": 0.9})[0], "pass")
        self.assertEqual(ev.judge(r, {"choice": "c", "confidence": 0.9})[0], "fail")
        self.assertEqual(ev.judge(r, {"choice": "a", "confidence": 0.3})[0], "fail")
        self.assertEqual(ev.judge(r, {"choice": "a"})[0], "error")
        self.assertEqual(ev.judge(r, {"choice": "zzz", "confidence": 1})[0], "error")
        self.assertEqual(ev.judge(r, {"choice": "a", "confidence": 2})[0], "error")

    def test_score(self):
        r = {"id": "s", "type": "score", "levels": ["low", "mid", "high"], "pass": {"min": 2}}
        self.assertEqual(ev.judge(r, {"score": 2})[0], "pass")
        self.assertEqual(ev.judge(r, {"score": 1})[0], "fail")
        self.assertEqual(ev.judge(r, {"score": 4})[0], "error")
        self.assertEqual(ev.judge(r, {"score": 2.5})[0], "error")
        self.assertEqual(ev.judge(r, {"score": True})[0], "error")
        r["pass"] = {"max": 1}
        self.assertEqual(ev.judge(r, {"score": 2})[0], "fail")


class Overall(unittest.TestCase):
    def v(self, verdict, sev="block"):
        return {"verdict": verdict, "severity": sev}

    def test_rules(self):
        self.assertEqual(ev.overall([self.v("pass"), self.v("fail", "warn")]), "pass")
        self.assertEqual(ev.overall([self.v("pass"), self.v("fail")]), "fail")
        self.assertEqual(ev.overall([self.v("error"), self.v("pass")]), "incomplete")
        self.assertEqual(ev.overall([self.v("pending", "warn")]), "pass")
        self.assertEqual(ev.overall([self.v("fail"), self.v("error")]), "fail")
        self.assertEqual(ev.overall([]), "pass")


class Cli(unittest.TestCase):
    def run_cli(self, *args, stdin=None):
        p = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, input=stdin)
        return p.returncode, json.loads(p.stdout)

    def test_check_then_verdict(self):
        rules = str(ROOT / "examples" / "rules")
        code, out = self.run_cli("check", "--rules", rules, "--state", "Fix the login redirect.")
        self.assertEqual(code, 3)
        self.assertEqual({r["id"] for r in out["resolved"]}, {"no-aws-key", "short-enough"})
        self.assertEqual({p["id"] for p in out["pending"]}, {"states-a-goal", "request-kind", "clarity"})
        self.assertIn("answer_format", out)
        with tempfile.TemporaryDirectory() as d:
            c, a = Path(d, "c.json"), Path(d, "a.json")
            c.write_text(json.dumps(out))
            a.write_text(json.dumps({"states-a-goal": {"noul": 0.9}, "request-kind": {"choice": "bug", "confidence": 0.8},
                                     "clarity": {"score": 3}}))
            code, v = self.run_cli("verdict", "--checked", str(c), "--answers", str(a))
            self.assertEqual((code, v["overall"], v["failed"]), (0, "pass", []))
            a.write_text(json.dumps({"states-a-goal": {"noul": 0.1}, "request-kind": {"choice": "bug", "confidence": 0.8},
                                     "clarity": {"score": 1}}))
            code, v = self.run_cli("verdict", "--checked", str(c), "--answers", str(a))
            self.assertEqual((code, v["overall"], v["failed"], v["warned"]), (1, "fail", ["states-a-goal"], ["clarity"]))
            a.write_text("{}")
            code, v = self.run_cli("verdict", "--checked", str(c), "--answers", str(a))
            self.assertEqual((code, v["overall"]), (3, "incomplete"))

    def test_check_state_from_stdin_and_early_fail(self):
        code, out = self.run_cli("check", "--rules", str(ROOT / "examples" / "rules"), "--state", "-",
                                 stdin="key AKIAABCDEFGHIJKLMNOP")
        self.assertEqual(code, 1)
        self.assertEqual([r["id"] for r in out["resolved"] if r["verdict"] == "fail"], ["no-aws-key"])

    def test_bad_rules_exit_2(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "x.toml").write_text('[[rule]]\nid="x"\ntype="zzz"\n')
            code, out = self.run_cli("check", "--rules", d, "--state", "hi")
            self.assertEqual(code, 2)
            self.assertTrue(out["errors"])
            code, out = self.run_cli("validate", "--rules", d)
            self.assertEqual(code, 2)

    def test_selftest_blind_then_graded(self):
        rules = str(ROOT / "examples" / "rules")
        code, out = self.run_cli("selftest", "--rules", rules)
        self.assertEqual(code, 3)
        self.assertEqual(out["ok"], 2)  # the two deterministic examples
        self.assertEqual([p["key"] for p in out["pending"]], ["states-a-goal#0", "states-a-goal#1"])
        self.assertTrue(all("expect" not in p for p in out["pending"]))
        with tempfile.TemporaryDirectory() as d:
            a = Path(d, "a.json")
            a.write_text(json.dumps({"states-a-goal#0": {"noul": 0.9}, "states-a-goal#1": {"noul": 0.1}}))
            code, out = self.run_cli("selftest", "--rules", rules, "--answers", str(a))
            self.assertEqual((code, out["ok"], out["failed"]), (0, 4, []))
            a.write_text(json.dumps({"states-a-goal#0": {"noul": 0.1}, "states-a-goal#1": {"noul": 0.1}}))
            code, out = self.run_cli("selftest", "--rules", rules, "--answers", str(a))
            self.assertEqual((code, [f["key"] for f in out["failed"]]), (1, ["states-a-goal#0"]))


if __name__ == "__main__":
    unittest.main()
