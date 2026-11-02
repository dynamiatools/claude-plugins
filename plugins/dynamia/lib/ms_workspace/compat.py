"""Python version gate. Must stay importable on old interpreters, so no modern syntax here."""
import sys

MIN = (3, 11)
QUIET_HOOKS = ("context", "images", "setupcheck")  # hooks that must never print errors into a session


def check(argv, version=None):
    """Return an exit code to stop with, or None to continue.

    `guard` keeps working on older Pythons (it does not read TOML). Other hook commands exit quietly,
    and everything else explains what is needed."""
    version = tuple(version or sys.version_info[:2])
    if version >= MIN:
        return None
    cmd = argv[0] if argv else ""
    if cmd == "guard":
        return None
    if cmd in QUIET_HOOKS:
        return 0
    sys.stderr.write("ms-workspace needs Python >= %d.%d (found %d.%d). Install a newer python3 and make it first in PATH.\n"
                     % (MIN + tuple(version)[:2]))
    return 1
