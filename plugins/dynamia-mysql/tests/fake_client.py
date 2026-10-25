#!/usr/bin/env python3
"""Stand-in for the mysql client: logs argv, stdin and the option file, answers from FAKE_RESP (regex -> output)."""
import json
import os
import re
import stat
import sys

import time

args = sys.argv[1:]
if "--version" in args:
    print(os.environ.get("FAKE_VERSION", "mysql  Ver 8.4.3 for Linux on x86_64"))
    sys.exit(0)
sql = sys.stdin.read()
cnf = next((a.split("=", 1)[1] for a in args if a.startswith("--defaults-extra-file=")), None)
entry = {"args": args, "sql": sql, "cnf": None}
if cnf:
    with open(cnf) as fh:
        entry["cnf"] = {"mode": stat.S_IMODE(os.stat(cnf).st_mode), "text": fh.read()}
with open(os.environ["FAKE_LOG"], "a") as fh:
    fh.write(json.dumps(entry) + "\n")
if os.environ.get("FAKE_SLEEP"):
    time.sleep(float(os.environ["FAKE_SLEEP"]))
if os.environ.get("FAKE_FAIL"):
    print(os.environ["FAKE_FAIL"], file=sys.stderr)
    sys.exit(1)
with open(os.environ["FAKE_RESP"]) as fh:
    responses = json.load(fh)
for pat, out in responses.items():
    if re.search(pat, sql, re.I):
        sys.stdout.write(out)
        break
