"""gh-lite: GitHub issue and PR state as compact JSON, through the `gh` CLI. Read-only."""
import json
import os

from mcplib import Tool, ToolFail, run, serve

GH = os.environ.get("DYNAMIA_GH", "gh")
BAD = {"FAILURE", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "ERROR", "STARTUP_FAILURE"}


def gh_json(argv: list[str]):
    r = run([GH, *argv])
    if r.returncode != 0:
        raise ToolFail(r.stderr.strip() or f"gh exited {r.returncode}")
    return json.loads(r.stdout or "null")


def count(args: dict, key: str = "numbers") -> list[int]:
    nums = args.get(key)
    if not isinstance(nums, list) or not all(isinstance(n, int) for n in nums):
        raise ToolFail(f"{key} must be a list of integers")
    if len(nums) > 50:
        raise ToolFail("at most 50 at a time")
    return nums


def check_rows(rollup: list[dict]) -> list[dict]:
    """One row per check, from either kind of entry statusCheckRollup holds."""
    rows = []
    for c in rollup or []:
        done = c.get("status", "COMPLETED") == "COMPLETED"
        result = c.get("conclusion") or c.get("state") or ""
        rows.append({"name": c.get("name") or c.get("context") or "?", "state": result if done else "PENDING"})
    return rows


def check_summary(rollup: list[dict]) -> dict:
    rows = check_rows(rollup)
    failing = [r["name"] for r in rows if r["state"] in BAD]
    pending = [r["name"] for r in rows if r["state"] in ("PENDING", "QUEUED", "IN_PROGRESS", "EXPECTED")]
    return {"total": len(rows), "failing": failing, "pending": pending, "ok": not failing and not pending}


def issue_state(args: dict):
    out = []
    for n in count(args):
        try:
            d = gh_json(["issue", "view", str(n), "--json", "number,state,title,labels,url"])
            out.append({"n": d["number"], "state": d["state"], "title": d["title"], "labels": [l["name"] for l in d["labels"]], "url": d["url"]})
        except ToolFail as e:
            out.append({"n": n, "error": str(e)})
    return out


def pr_status(args: dict):
    n = args["number"]
    d = gh_json(["pr", "view", str(n), "--json",
                 "number,title,state,isDraft,mergeable,reviewDecision,headRefName,baseRefName,statusCheckRollup,closingIssuesReferences,url"])
    return {
        "n": d["number"], "title": d["title"], "state": d["state"], "draft": d["isDraft"],
        "mergeable": d["mergeable"], "review": d["reviewDecision"] or "NONE",
        "head": d["headRefName"], "base": d["baseRefName"], "url": d["url"],
        "checks": check_summary(d["statusCheckRollup"]),
        "closes": [i["number"] for i in d["closingIssuesReferences"] or []],
    }


def checks(args: dict):
    d = gh_json(["pr", "view", str(args["number"]), "--json", "statusCheckRollup"])
    rows = check_rows(d["statusCheckRollup"])
    return {**check_summary(d["statusCheckRollup"]), "rows": [r for r in rows if r["state"] in BAD or r["state"] == "PENDING"]}


def issues_closed_by(args: dict):
    d = gh_json(["pr", "view", str(args["number"]), "--json", "closingIssuesReferences,state"])
    return {"state": d["state"], "closes": [i["number"] for i in d["closingIssuesReferences"] or []]}


NUM = {"type": "integer", "description": "PR number"}
TOOLS = {
    "issue_state": Tool("State, title and labels of several issues in one call. A failed one comes back as {n, error}.",
                        {"numbers": {"type": "array", "items": {"type": "integer"}}}, issue_state, ("numbers",)),
    "pr_status": Tool("One PR: state, draft, mergeable, review decision, checks summary and the issues it closes.",
                      {"number": NUM}, pr_status, ("number",)),
    "checks": Tool("CI checks of a PR: counts, and only the failing and pending ones by name.",
                   {"number": NUM}, checks, ("number",)),
    "issues_closed_by": Tool("Issue numbers a PR closes, and the PR state (a merged PR has closed them).",
                             {"number": NUM}, issues_closed_by, ("number",)),
}

if __name__ == "__main__":
    serve("gh-lite", TOOLS)
