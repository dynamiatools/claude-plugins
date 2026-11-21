"""`ms-workspace flash on|off <session-id>`: the pointer file that makes the status line show the FLASH badge."""
import re
import sys

from .usage import cache_dir


def cmd_flash(args: list[str]) -> int:
    if len(args) != 2 or args[0] not in ("on", "off"):
        print("usage: ms-workspace flash on|off <session-id>", file=sys.stderr)
        return 2
    sid = re.sub(r"[^A-Za-z0-9_-]", "", args[1])
    if not sid:
        return 0  # no session id (not run by Claude Code): the badge is cosmetic, never fail
    path = cache_dir() / "flash" / f"{sid}.json"
    if args[0] == "on":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"status": "running"}')
    else:
        path.unlink(missing_ok=True)
    return 0
