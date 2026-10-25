import os
import tempfile
import unittest

from _load import load

parity = load("remix-parity")
HEAD = "feature,area,priority,original,clone,notes\n"


def score(body):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "f.csv")
        open(p, "w").write(HEAD + body)
        return parity.score(parity.load(p))


class ParityTest(unittest.TestCase):
    def test_weights_and_partial(self):
        s = score("a,x,must,yes,yes,\nb,x,should,yes,partial,\nc,y,could,yes,no,\n")
        self.assertEqual(s["pct"], round((3 + 1) / 6 * 100))
        self.assertEqual(s["musts"], (1, 1))

    def test_skip_and_added_are_not_scored(self):
        s = score("a,x,must,yes,yes,\nb,x,must,yes,skip,licensed\nc,x,could,no,yes,mine\n")
        self.assertEqual(s["pct"], 100)
        self.assertEqual(len(s["skipped"]), 1)
        self.assertEqual(len(s["added"]), 1)

    def test_missing_in_build_order(self):
        s = score("a,x,could,yes,no,\nb,x,must,yes,no,\n")
        self.assertEqual([r["feature"] for r in s["missing"]], ["b", "a"])

    def test_must_not_done_fails_exit(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "f.csv")
            open(p, "w").write(HEAD + "a,x,must,yes,partial,\n")
            self.assertEqual(parity.main([p]), 1)
            open(p, "w").write(HEAD + "a,x,must,yes,yes,\n")
            self.assertEqual(parity.main([p]), 0)
            self.assertEqual(parity.main([p, "--fail-under", "101"]), 1)

    def test_bad_values_are_errors(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "f.csv")
            open(p, "w").write(HEAD + "a,x,urgent,yes,yes,\n")
            self.assertEqual(parity.main([p]), 2)


if __name__ == "__main__":
    unittest.main()
