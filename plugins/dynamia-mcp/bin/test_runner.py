"""test-runner: run a test command and return only what failed, not the log. Writes nothing itself, but runs project code."""
import os
import re
import shlex
from pathlib import Path

from mcplib import Tool, ToolFail, run, serve

ROOT = Path(os.environ.get("DYNAMIA_ROOT", os.getcwd())).resolve()
ALLOWED = {"mvn", "./mvnw", "gradle", "./gradlew", "bun", "npm", "pnpm", "yarn", "npx", "vitest", "jest", "pytest", "python", "python3", "go", "cargo", "dotnet"}
MAX_FAILURES = 20

SUMMARY = [
    re.compile(r"^(?:\[\w+\] )?Tests run: \d+, Failures: \d+.*$"),            # surefire, the total has no " - in Class"
    re.compile(r"^Ran \d+ tests? in .*$"),                        # unittest
    re.compile(r"^=+ .*(?:passed|failed).* =+$"),                 # pytest
    re.compile(r"^\s*\d+ (?:pass|fail)\s*$"),                     # bun
    re.compile(r"^Tests:\s+.*total.*$"),                          # jest
    re.compile(r"^(?:ok|FAIL)\s+\S+\s+[\d.]+s.*$"),               # go
]
FAIL_LINE = [
    re.compile(r"^\[ERROR\]\s{2,}(?P<test>\w[\w.$]*Test\w*\.\w+(?::\d+)?)\s*(?P<msg>.*)$"),   # surefire
    re.compile(r"^(?:FAIL|ERROR): (?P<test>\S+ \([\w.]+\))\s*(?P<msg>.*)$"),                  # unittest
    re.compile(r"^FAILED (?P<test>\S+::\S+)(?: - (?P<msg>.*))?$"),                                 # pytest
    re.compile(r"^\(fail\) (?P<test>.+?)(?: \[[\d.]+ms\])?$"),                                # bun
    re.compile(r"^\s*(?:●|✕|×) (?P<test>.+)$"),                                               # jest, vitest
    re.compile(r"^--- FAIL: (?P<test>\S+).*$"),                                               # go
]
PROBLEM = re.compile(r"^(?:\[ERROR\]|ERROR|error[: ]|.*Exception:|.*COMPILATION ERROR)")


def parse(output: str, exit_code: int) -> dict:
    lines = output.splitlines()
    summary = next((re.sub(r"^\[\w+\] ", "", l.strip()) for l in reversed(lines) for p in SUMMARY if p.match(l)), "")
    failures, seen = [], set()
    for l in lines:
        for p in FAIL_LINE:
            m = p.match(l)
            if m and m.group("test") not in seen and len(failures) < MAX_FAILURES:
                seen.add(m.group("test"))
                failures.append({"test": m.group("test"), "msg": ((m.groupdict().get("msg") or "").strip())[:200]})
                break
    result = {"exit": exit_code, "passed": exit_code == 0, "summary": summary, "failures": failures}
    if exit_code != 0 and not failures:
        # No test failed by name: a build or setup error. Show its first problem lines, then the tail.
        result["problems"] = [l.strip()[:200] for l in lines if PROBLEM.match(l)][:10]
        result["tail"] = [l[:200] for l in lines[-15:]]
    return result


def run_tests(args: dict):
    argv = shlex.split(args["command"])
    if not argv or argv[0] not in ALLOWED:
        raise ToolFail(f"command must start with one of: {', '.join(sorted(ALLOWED))}")
    cwd = (ROOT / args.get("cwd", ".")).resolve()
    if ROOT not in cwd.parents and cwd != ROOT:
        raise ToolFail("cwd is outside the project")
    timeout = min(int(args.get("timeout", 600)), 1800)
    r = run(argv, cwd=str(cwd), timeout=timeout)

    return parse(r.stdout + "\n" + r.stderr, r.returncode)


TOOLS = {
    "run": Tool(
        "Run a test command (mvn, gradle, bun, npm, pytest, python -m unittest, go, cargo ...) and return exit code, the summary line and only the failing tests with their message. A build error returns its first problem lines and the tail.",
        {"command": {"type": "string"}, "cwd": {"type": "string", "description": "Folder inside the project"}, "timeout": {"type": "integer", "description": "Seconds, default 600, max 1800"}},
        run_tests, ("command",), read_only=False,
    ),
}

if __name__ == "__main__":
    serve("test-runner", TOOLS)
