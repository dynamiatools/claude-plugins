#!/usr/bin/env python3
"""dynamia-eval: evaluate a text against local rules (Python 3.11+, standard library).

The contract follows the idea of a structured evaluator: a state, typed questions
(noul = true/false probability, choice = one option, score = a level) and a verdict
per rule. The script never calls a model. Rules with a deterministic `check` are
resolved here; the rest come back as `pending` for a judge (Claude, in the session)
to answer, and `verdict` applies each rule's thresholds to those answers.

  eval.py validate --rules DIR|FILE
  eval.py check    --rules DIR|FILE (--state TEXT | --state-file F | --state -)
  eval.py verdict  --checked FILE|- --answers FILE
  eval.py selftest --rules DIR|FILE [--answers FILE]

Exit codes: 0 pass, 1 fail, 2 bad rules or usage, 3 incomplete (answers missing or invalid).
"""
import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

DEFAULT_RULES = ".dynamia-eval/rules"
TYPES = ("noul", "choice", "score")
SEVERITIES = ("block", "warn")
CHECK_KEYS = {"regex", "expect", "ignore_case", "min_chars", "max_chars"}
RULE_KEYS = {"id", "type", "instructions", "criteria", "options", "levels", "check", "pass",
             "severity", "source", "example"}
PASS_KEYS = {"noul": {"min", "max"}, "choice": {"accept", "min_confidence"}, "score": {"min", "max"}}
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
ANSWER_FORMAT = {
    "noul": {"noul": "number 0..1, the probability that the statement is true"},
    "choice": {"choice": "one of options", "confidence": "number 0..1"},
    "score": {"score": "integer 1..len(levels), 1 is the first level", "confidence": "number 0..1"},
}


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def is_str_list(v, minimum=0):
    return isinstance(v, list) and len(v) >= minimum and all(isinstance(x, str) and x for x in v)


# --- rules -------------------------------------------------------------------

def validate_rule(r):
    """Returns the list of problems of one rule (empty when valid)."""
    if not isinstance(r, dict):
        return ["rule must be a table"]
    errs = []
    for k in sorted(set(r) - RULE_KEYS):
        errs.append(f"unknown key '{k}'")
    rid, t = r.get("id"), r.get("type")
    if not isinstance(rid, str) or not ID_RE.match(rid):
        errs.append("id must be lowercase letters, digits, '-' or '_'")
    if t not in TYPES:
        errs.append(f"type must be one of {', '.join(TYPES)}")
        return errs
    if r.get("severity", "block") not in SEVERITIES:
        errs.append(f"severity must be one of {', '.join(SEVERITIES)}")
    check = r.get("check")
    if check is not None:
        errs += _validate_check(r, check)
        if "pass" in r:
            errs.append("pass is ignored when check is set; remove one")
    elif not isinstance(r.get("instructions"), str) or not r["instructions"].strip():
        errs.append("a rule without check needs instructions for the judge")
    if check is None:
        errs += _validate_pass(r, t)
    for key in ("instructions", "criteria", "source"):
        if key in r and not isinstance(r[key], str):
            errs.append(f"{key} must be a string")
    examples = r.get("example", [])
    if not isinstance(examples, list):
        errs.append("example must be an array of tables")
        examples = []
    for i, ex in enumerate(examples):
        if not isinstance(ex, dict) or not isinstance(ex.get("state"), str) or ex.get("expect") not in ("pass", "fail"):
            errs.append(f"example {i}: needs state (string) and expect ('pass' or 'fail')")
    return errs


def _validate_check(r, check):
    errs = []
    if r["type"] != "noul":
        return ["check is only allowed on noul rules"]
    if not isinstance(check, dict):
        return ["check must be a table"]
    for k in sorted(set(check) - CHECK_KEYS):
        errs.append(f"check: unknown key '{k}'")
    if not ({"regex", "min_chars", "max_chars"} & set(check)):
        errs.append("check needs regex, min_chars or max_chars")
    if "regex" in check:
        try:
            re.compile(check["regex"])
        except (re.error, TypeError) as e:
            errs.append(f"check: bad regex ({e})")
        if check.get("expect") not in ("present", "absent"):
            errs.append("check: expect must be 'present' or 'absent' when regex is set")
    for k in ("min_chars", "max_chars"):
        if k in check and (not isinstance(check[k], int) or isinstance(check[k], bool) or check[k] < 0):
            errs.append(f"check: {k} must be an integer >= 0")
    return errs


def _validate_pass(r, t):
    errs = []
    p = r.get("pass", {})
    if not isinstance(p, dict):
        return ["pass must be a table"]
    for k in sorted(set(p) - PASS_KEYS[t]):
        errs.append(f"pass: unknown key '{k}' for {t}")
    if t == "noul":
        for k in ("min", "max"):
            if k in p and (not is_num(p[k]) or not 0 <= p[k] <= 1):
                errs.append(f"pass: {k} must be a number 0..1")
    elif t == "choice":
        if not is_str_list(r.get("options"), 2) or len(set(r["options"])) != len(r["options"]):
            errs.append("choice needs options: at least 2 distinct strings")
        elif not is_str_list(p.get("accept"), 1) or not set(p["accept"]) <= set(r["options"]):
            errs.append("pass.accept must list at least one of the options")
        if "min_confidence" in p and (not is_num(p["min_confidence"]) or not 0 <= p["min_confidence"] <= 1):
            errs.append("pass: min_confidence must be a number 0..1")
    else:
        levels = r.get("levels")
        if not is_str_list(levels, 2):
            errs.append("score needs levels: at least 2 strings, lowest first")
        elif not ({"min", "max"} & set(p)):
            errs.append("score needs pass.min or pass.max")
        else:
            for k in ("min", "max"):
                if k in p and (not isinstance(p[k], int) or isinstance(p[k], bool) or not 1 <= p[k] <= len(levels)):
                    errs.append(f"pass: {k} must be an integer 1..{len(levels)}")
    return errs


def load_rules(path):
    """Returns (rules, errors) from a .toml file or a folder of them."""
    p = Path(path)
    files = sorted(p.glob("*.toml")) if p.is_dir() else [p]
    if not files or (not p.exists()):
        return [], [f"no rules found at {path}"]
    rules, errors, seen = [], [], {}
    for f in files:
        try:
            data = tomllib.loads(f.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError) as e:
            errors.append(f"{f.name}: {e}")
            continue
        for k in sorted(set(data) - {"rule"}):
            errors.append(f"{f.name}: unknown top-level key '{k}'")
        for i, r in enumerate(data.get("rule", [])):
            where = f"{f.name} rule {r.get('id', i + 1) if isinstance(r, dict) else i + 1}"
            problems = validate_rule(r)
            errors += [f"{where}: {m}" for m in problems]
            if problems:
                continue
            if r["id"] in seen:
                errors.append(f"{where}: duplicate id (also in {seen[r['id']]})")
                continue
            seen[r["id"]] = f.name
            rules.append(r)
    return rules, errors


# --- evaluation --------------------------------------------------------------

def run_check(rule, state):
    """Deterministic rule: returns (verdict, detail)."""
    c = rule["check"]
    if "regex" in c:
        found = re.search(c["regex"], state, re.IGNORECASE if c.get("ignore_case") else 0)
        if (c["expect"] == "present") != bool(found):
            return "fail", f"pattern {'not found' if c['expect'] == 'present' else 'found'}" + (
                f": {found.group(0)[:40]!r}" if found else "")
    if "min_chars" in c and len(state) < c["min_chars"]:
        return "fail", f"{len(state)} chars, needs >= {c['min_chars']}"
    if "max_chars" in c and len(state) > c["max_chars"]:
        return "fail", f"{len(state)} chars, needs <= {c['max_chars']}"
    return "pass", ""


def effective_pass(rule):
    p = dict(rule.get("pass", {}))
    if rule["type"] == "noul" and not ({"min", "max"} & set(p)):
        p["min"] = 0.5
    return p


def judge(rule, ans):
    """Applies a rule's thresholds to a judge answer: returns (verdict, detail)."""
    t, p = rule["type"], effective_pass(rule)
    if not isinstance(ans, dict):
        return "error", "answer must be an object"
    if t == "noul":
        v = ans.get("noul")
        v = float(v) if isinstance(v, bool) else v
        if not is_num(v) or not 0 <= v <= 1:
            return "error", "noul must be a number 0..1"
        if "min" in p and v < p["min"]:
            return "fail", f"noul={v:g}, needs >= {p['min']:g}"
        if "max" in p and v > p["max"]:
            return "fail", f"noul={v:g}, needs <= {p['max']:g}"
        return "pass", f"noul={v:g}"
    conf = ans.get("confidence")
    if conf is not None and (not is_num(conf) or not 0 <= conf <= 1):
        return "error", "confidence must be a number 0..1"
    if t == "choice":
        c = ans.get("choice")
        if c not in rule["options"]:
            return "error", f"choice must be one of {rule['options']}"
        if "min_confidence" in p:
            if conf is None:
                return "error", "confidence is required by this rule"
            if conf < p["min_confidence"]:
                return "fail", f"confidence={conf:g}, needs >= {p['min_confidence']:g}"
        if c not in p["accept"]:
            return "fail", f"choice={c}, accepted: {', '.join(p['accept'])}"
        return "pass", f"choice={c}"
    s = ans.get("score")
    if not isinstance(s, int) or isinstance(s, bool) or not 1 <= s <= len(rule["levels"]):
        return "error", f"score must be an integer 1..{len(rule['levels'])}"
    if "min" in p and s < p["min"]:
        return "fail", f"score={s} ({rule['levels'][s - 1]}), needs >= {p['min']}"
    if "max" in p and s > p["max"]:
        return "fail", f"score={s} ({rule['levels'][s - 1]}), needs <= {p['max']}"
    return "pass", f"score={s} ({rule['levels'][s - 1]})"


def pending_item(rule):
    item = {"id": rule["id"], "type": rule["type"], "instructions": rule.get("instructions", ""),
            "pass": effective_pass(rule), "severity": rule.get("severity", "block")}
    for k in ("criteria", "options", "levels"):
        if k in rule:
            item[k] = rule[k]
    return item


def overall(verdicts):
    blocking = [v for v in verdicts if v["severity"] == "block"]
    if any(v["verdict"] == "fail" for v in blocking):
        return "fail"
    if any(v["verdict"] in ("error", "pending") for v in blocking):
        return "incomplete"
    return "pass"


EXIT = {"pass": 0, "fail": 1, "incomplete": 3}


def emit(obj, code):
    print(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
    return code


def read_json(path):
    return json.load(sys.stdin if path == "-" else open(path, encoding="utf-8"))


# --- commands ----------------------------------------------------------------

def cmd_validate(a):
    rules, errors = load_rules(a.rules)
    return emit({"rules": len(rules), "errors": errors}, 2 if errors else 0)


def cmd_check(a):
    rules, errors = load_rules(a.rules)
    if errors:
        return emit({"errors": errors}, 2)
    if a.state_file:
        state = Path(a.state_file).read_text(encoding="utf-8")
    elif a.state == "-":
        state = sys.stdin.read()
    else:
        state = a.state
    resolved, pending = [], []
    for r in rules:
        if "check" in r:
            v, d = run_check(r, state)
            resolved.append({"id": r["id"], "verdict": v, "severity": r.get("severity", "block"),
                             "by": "check", "detail": d})
        else:
            pending.append(pending_item(r))
    out = {"resolved": resolved, "pending": pending}
    if pending:
        out["answer_format"] = ANSWER_FORMAT
    state_so_far = overall(resolved)
    return emit(out, 3 if pending and state_so_far == "pass" else EXIT[state_so_far])


def cmd_verdict(a):
    checked, answers = read_json(a.checked), read_json(a.answers)
    verdicts = list(checked.get("resolved", []))
    for item in checked.get("pending", []):
        sev = item.get("severity", "block")
        if item["id"] not in answers:
            verdicts.append({"id": item["id"], "verdict": "pending", "severity": sev, "by": "judge",
                             "detail": "no answer"})
            continue
        v, d = judge(item, answers[item["id"]])
        verdicts.append({"id": item["id"], "verdict": v, "severity": sev, "by": "judge", "detail": d})
    result = overall(verdicts)
    return emit({"overall": result, "verdicts": verdicts,
                 "failed": [v["id"] for v in verdicts if v["verdict"] == "fail" and v["severity"] == "block"],
                 "warned": [v["id"] for v in verdicts if v["verdict"] == "fail" and v["severity"] == "warn"]},
                EXIT[result])


def cmd_selftest(a):
    rules, errors = load_rules(a.rules)
    if errors:
        return emit({"errors": errors}, 2)
    answers = read_json(a.answers) if a.answers else {}
    ok, failed, pending = [], [], []
    for r in rules:
        for i, ex in enumerate(r.get("example", [])):
            key = f"{r['id']}#{i}"
            if "check" in r:
                v, d = run_check(r, ex["state"])
            elif key in answers:
                v, d = judge(r, answers[key])
            else:
                # expect is withheld on purpose: the judge must answer blind
                pending.append({"key": key, "state": ex["state"], **pending_item(r)})
                continue
            row = {"key": key, "expect": ex["expect"], "got": v, "detail": d}
            (ok if v == ex["expect"] else failed).append(row)
    out = {"ok": len(ok), "failed": failed, "pending": pending}
    if pending:
        out["answer_format"] = ANSWER_FORMAT
    return emit(out, 1 if failed else 3 if pending else 0)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("validate", cmd_validate), ("check", cmd_check), ("selftest", cmd_selftest)):
        p = sub.add_parser(name)
        p.add_argument("--rules", default=DEFAULT_RULES)
        if name == "check":
            g = p.add_mutually_exclusive_group(required=True)
            g.add_argument("--state")
            g.add_argument("--state-file")
        if name == "selftest":
            p.add_argument("--answers")
        p.set_defaults(fn=fn)
    p = sub.add_parser("verdict")
    p.add_argument("--checked", required=True)
    p.add_argument("--answers", required=True)
    p.set_defaults(fn=cmd_verdict)
    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except (OSError, json.JSONDecodeError, KeyError, UnicodeDecodeError) as e:
        return emit({"errors": [f"{type(e).__name__}: {e}"]}, 2)


if __name__ == "__main__":
    sys.exit(main())
