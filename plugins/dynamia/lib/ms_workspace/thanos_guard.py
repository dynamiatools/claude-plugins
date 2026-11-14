"""Strict command profile for a THANOS mission (an autonomous run inside its own batch worktree).

`verdict(command, mission)` returns one of:
    ("block", reason)   the command could change something outside the batch, publish, or destroy: refused for good
    ("allow", "")       every part of it is on the short list of known-safe commands: approved without a prompt
    ("", "")            anything else: the normal permissions decide (a prompt unless the user allowlisted it)

It is a profile, not a sandbox: it stops mistakes and realistic variants, not a determined adversary. It never reads
workspace.toml to decide a block; the only configuration is the mission's own state (batch path, branch, deny_hosts)."""
from __future__ import annotations

import os
import re

from .guard import SHELLS, _git_subcommand, _segments, _strip

NEVER = {"sudo", "su", "doas", "pkexec", "runuser"}
REMOTE = {"ssh", "scp", "sftp", "rsync", "mosh", "nc", "ncat", "telnet", "ftp", "lftp", "kubectl", "helm", "terraform", "tofu", "ansible",
          "ansible-playbook", "ansible-vault", "aws", "gcloud", "gsutil", "az", "doctl", "flyctl", "fly", "heroku", "vercel", "netlify",
          "wrangler", "pulumi", "packer", "vagrant", "twine", "gh", "glab", "hub"}
DESTROY = {"kill", "pkill", "killall", "chown", "chgrp", "mkfs", "fdisk", "parted", "shutdown", "reboot", "halt", "poweroff", "systemctl",
           "service", "crontab", "dd", "shred", "mount", "umount", "iptables", "ufw", "passwd", "useradd", "userdel", "visudo"}
READONLY = {"ls", "cat", "head", "tail", "wc", "grep", "egrep", "fgrep", "rg", "sort", "uniq", "diff", "cmp", "stat", "file", "echo", "printf",
            "pwd", "date", "which", "type", "true", "false", "test", "[", "basename", "dirname", "realpath", "readlink", "cut", "tr", "awk",
            "jq", "column", "tree", "du", "df", "uname", "whoami", "id", "hostname", "sleep", "seq", "expr", "md5sum", "sha1sum", "sha256sum",
            "nl", "rev", "od", "xxd", "hexdump", "printenv", "nproc", "free", "uptime", "ps", "lsof", "ss", "sed", "find", "wait", ":"}
WRITERS = {"mkdir", "touch", "cp", "mv", "ln", "tee", "chmod", "install", "truncate"}
BUILD = {"mvn", "mvnw", "gradle", "gradlew"}
NODEPM = {"pnpm", "npm", "yarn", "bun"}
NODE_OK = {"test", "t", "run", "run-script", "install", "i", "ci", "build", "lint", "list", "ls", "outdated", "why", "audit", "add", "remove",
           "rm", "uninstall", "--version", "-v", "install-test", "-r", "--filter"}
NODE_BLOCK = {"publish", "login", "adduser", "logout", "unpublish", "deprecate", "owner", "access", "token", "dist-tag", "team", "org", "whoami"}
GIT_SAFE = {"status", "diff", "log", "show", "add", "commit", "rev-parse", "rev-list", "ls-files", "ls-tree", "cat-file", "blame", "shortlog",
            "describe", "merge", "cherry-pick", "rebase", "fetch", "switch", "tag", "grep", "diff-tree", "merge-base", "show-ref",
            "for-each-ref", "name-rev", "bisect", "apply", "am", "mv", "merge-tree", "count-objects", "check-ignore", "ls-remote", "version"}
GIT_NEVER = {"gc", "prune", "filter-branch", "filter-repo", "replace", "send-pack", "svn", "fast-import"}
GH_READ = {"issue": {"view", "list", "status"}, "pr": {"view", "list", "checks", "diff", "status"}, "repo": {"view"},
           "run": {"view", "list"}, "release": {"view", "list"}}
MS_SAFE = {"status", "log", "usage", "plan", "test", "integrate", "affected", "context", "memory", "recall", "doctor", "gate", "budget",
           "insights", "tokens", "thanos", "handoff", "modules", "junit", "sys", "images", "claude-md", "open", "contract"}
MS_BLOCK = {"ship", "clean", "undo", "promote", "setup-hooks", "notify", "batch", "branch", "release"}
CURL_WRITE = re.compile(r"(^|\s)(-X\s*(POST|PUT|DELETE|PATCH)|--request\s+(POST|PUT|DELETE|PATCH)|-d\b|--data\S*|-F\b|--form\b|-T\b|--upload-file|--json\b)", re.I)
PIPE_TO_SHELL = re.compile(r"\|\s*(sudo\s+)?(ba|z|da|k)?sh\b")
SQL_DESTROY = re.compile(r"\b(drop|truncate)\s+(table|database|schema|user)\b|\bdelete\s+from\s+\S+\s*(;|\"|'|$)", re.I)
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def _roots(m: dict) -> list[str]:
    scratch = f"/tmp/claude-{os.getuid()}" if hasattr(os, "getuid") else "/tmp/claude"
    return [os.path.realpath(m["batch_path"]), scratch]


def inside(path: str, m: dict, cwd: str) -> bool:
    if path in ("/dev/null", "/dev/stderr", "/dev/stdout"):
        return True
    p = os.path.expanduser(path)
    full = os.path.realpath(p if os.path.isabs(p) else os.path.join(cwd, p))
    return any(full == r or full.startswith(r + os.sep) for r in _roots(m))


def _operands(args: list[str]) -> list[str]:
    out, after = [], False
    for a in args:
        if after or not a.startswith("-"):
            out.append(a)
        elif a == "--":
            after = True
    return out


def _push(rest: list[str], m: dict, cwd: str) -> tuple[str, str]:
    """Only a plain push of the mission's own batch branch to origin (an offsite backup of what piled up)."""
    branch = m["branch"]
    pos = []
    for a in rest:
        if a.startswith("-"):
            if a not in ("-u", "--set-upstream", "-v", "--verbose", "-q", "--quiet", "--no-verify"):
                return "block", f"git push option {a}"
        else:
            pos.append(a)
    if len(pos) != 2 or pos[0] != "origin":
        return "block", f"git push must name the remote and the branch: git push -u origin {branch}"
    spec = pos[1]
    if spec == "HEAD":
        from .core import git_out
        spec = git_out(cwd, "branch", "--show-current")
    if spec not in (branch, f"refs/heads/{branch}", f"{branch}:{branch}", f"HEAD:{branch}"):
        return "block", f"THANOS may only push its own batch branch ({branch}), never '{pos[1]}'"
    return "safe", ""


def _git(args: list[str], m: dict, cwd: str) -> tuple[str, str]:
    for i, a in enumerate(args):
        if a == "-C" or a.startswith("-C") and len(a) > 2:
            target = args[i + 1] if a == "-C" and i + 1 < len(args) else a[2:]
            if not inside(target, m, cwd):
                return "block", "git -C outside the batch worktree"
            cwd = os.path.join(cwd, target) if not os.path.isabs(target) else target
        if a.startswith(("--git-dir", "--work-tree")):
            return "block", "git --git-dir/--work-tree"
    sub, rest = _git_subcommand(args)
    flags = [a for a in rest if a.startswith("-")]
    if sub == "push":
        return _push(rest, m, cwd)
    if sub in GIT_NEVER:
        return "block", f"git {sub}"
    if sub == "reset" and any(a in ("--hard", "--merge", "--keep") for a in rest):
        return "block", "git reset --hard discards work"
    if sub == "clean" and any(a == "--force" or (a.startswith("-") and not a.startswith("--") and "f" in a) for a in rest):
        return "block", "git clean -f deletes untracked files"
    if sub == "checkout" and ("--" in rest or "." in rest or any(a in ("-f", "--force") for a in rest)):
        return "block", "git checkout would discard changes"
    if sub == "branch" and any(a in ("-D", "-d", "--delete", "-m", "-M", "--move", "-f", "--force") for a in rest):
        mine = f"agent/{os.path.basename(m['batch_path'])}/"
        names = [a for a in rest if not a.startswith("-")]
        if any(a in ("-m", "-M", "--move", "-f", "--force") for a in rest) or not names or not all(n.startswith(mine) for n in names):
            return "block", "git branch -D/-m of a branch that is not one of this mission's task branches"
        return "safe", ""
    if sub == "stash" and rest[:1] in (["drop"], ["clear"]):
        return "block", "git stash drop/clear"
    if sub == "remote" and rest[:1] in (["add"], ["set-url"], ["remove"], ["rm"], ["rename"], ["prune"]):
        return "block", "git remote change"
    if sub == "worktree":
        return ("safe", "") if rest[:1] == ["list"] else ("block", "git worktree changes belong to ms-workspace")
    if sub == "reflog" and rest[:1] in (["expire"], ["delete"]):
        return "block", "git reflog expire/delete"
    if sub == "update-ref" and "-d" in rest:
        return "block", "git update-ref -d"
    if sub in ("reset", "clean", "checkout", "branch", "stash", "remote", "reflog") or sub in GIT_SAFE:
        return "safe", ""
    return "unknown", ""


def _ms(words: list[str], args: list[str]) -> tuple[str, str]:
    sub = words[0] if words else ""
    if sub in MS_BLOCK:
        return "block", f"ms-workspace {sub} is for the user, not for a THANOS mission"
    if sub == "env" and "--trust" in args:
        return "block", "ms-workspace env --trust"
    if sub == "ps" and words[1:2] == ["kill"]:
        return "block", "ms-workspace ps kill"
    if sub == "docker" and words[1:2] == ["clean"]:
        return "block", "ms-workspace docker clean"
    if sub == "dev-env" and words[1:2] in (["add"], ["rm"]):
        return "block", "ms-workspace dev-env changes the shared workspace.toml"
    if sub == "http" and words[1:2] in (["run"], ["bench"]):
        env = args[args.index("--env") + 1] if "--env" in args and args.index("--env") + 1 < len(args) else ""
        return ("safe", "") if env == "local" else ("block", "ms-workspace http run only against --env local")
    if sub == "http" and words[1:2] in (["list"], ["history"], ["show"], ["diff"]):
        return "safe", ""
    if sub == "mock" and words[1:2] in (["start"], ["stop"], ["status"], ["url"], ["list"], ["logs"]):
        return "safe", ""
    if sub == "ps" and words[1:2] in (["tree"], ["find"], ["ports"], ["leftovers"]):
        return "safe", ""
    if sub == "dev-env" and words[1:2] == ["list"]:
        return "safe", ""
    if sub == "open":
        return "unknown", ""
    if sub in MS_SAFE:
        return "safe", ""
    return "unknown", ""


def _classify(seg: list[str], m: dict, cwd: str, moved: bool, deny: list[str]) -> tuple[str, str, str, bool]:
    """(kind, reason, new cwd, moved) for one command."""
    raw = [t for t in seg if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", t)]
    if raw and os.path.basename(raw[0]) in NEVER:
        return "block", f"{os.path.basename(raw[0])}: no privilege escalation", cwd, moved
    seg = _strip(seg)
    if not seg:
        return "safe", "", cwd, moved
    prog, args = os.path.basename(seg[0]), seg[1:]
    words = [a for a in args if not a.startswith("-")]
    text = " ".join(seg)
    for host in deny:
        if host and host in text:
            return "block", f"'{host}' is on the deny list (production)", cwd, moved
    # redirections write files
    for i, t in enumerate(seg):
        mt = re.match(r"^\d*>>?(.*)$", t)
        if mt and not t.startswith(("<", "&")):
            target = mt.group(1) or (seg[i + 1] if i + 1 < len(seg) else "")
            if target and not inside(target, m, cwd):
                return "block", f"redirection writes outside the batch ({target})", cwd, moved
    if prog in SHELLS and "-c" in args and args.index("-c") + 1 < len(args):
        kind, why = verdict(args[args.index("-c") + 1], m, cwd=cwd, _depth=1)
        return {"allow": "safe", "block": "block"}.get(kind, "unknown"), why, cwd, moved
    if prog == "cd":
        target = words[0] if words else ""
        if not target or target == "-" or not inside(target, m, cwd):
            return "unknown", "", cwd, True
        new = os.path.realpath(os.path.expanduser(target) if os.path.isabs(os.path.expanduser(target)) else os.path.join(cwd, target))
        return "safe", "", new, moved
    if prog == "gh" and len(words) >= 2 and words[1] in GH_READ.get(words[0], ()) and "--web" not in args and "-w" not in args:
        return "safe", "", cwd, moved   # read-only lookups (issue text, PR state, CI checks) do not publish anything
    if prog in REMOTE:
        return "block", f"{prog} reaches machines or services outside the batch", cwd, moved
    if prog in DESTROY:
        return "block", f"{prog} is not allowed in a THANOS mission", cwd, moved
    if prog == "rm":
        recursive = any(a.startswith("-") and not a.startswith("--") and ("r" in a or "R" in a) or a == "--recursive" for a in args)
        top = os.path.realpath(m["batch_path"])
        for t in words:
            if not inside(t, m, cwd) or moved and not os.path.isabs(t):
                return "block", f"rm outside the batch ({t})", cwd, moved
            full = os.path.realpath(os.path.expanduser(t) if os.path.isabs(os.path.expanduser(t)) else os.path.join(cwd, t))
            if recursive and (full == top or os.path.dirname(full) == top or ".git" in full.split(os.sep) or t in (".", "..", "*")):
                return "block", f"recursive rm of {t}", cwd, moved
        return "safe", "", cwd, moved
    if prog in WRITERS or (prog == "sed" and any(a == "-i" or a.startswith("-i") or a == "--in-place" for a in args)):
        for t in words:
            if (prog == "chmod" and t == words[0]) and not os.sep in t:
                continue
            if moved and not os.path.isabs(t) or not inside(t, m, cwd):
                return "block", f"{prog} writes outside the batch ({t})", cwd, moved
        if prog == "chmod" and any(a.startswith("-") and "R" in a for a in args):
            return "block", "chmod -R", cwd, moved
        return "safe", "", cwd, moved
    if prog == "git":
        k, why = _git(args, m, cwd)
        return k, why, cwd, moved
    if prog == "ms-workspace":
        k, why = _ms(words, args)
        return k, why, cwd, moved
    if prog in BUILD:
        if any(re.search(r"(^|:)deploy$|release:|publish|uploadArchives|scm:|-Dmaven\.deploy|versions:commit", a, re.I) for a in args):
            return "block", f"{prog} deploy/publish/release", cwd, moved
        return "safe", "", cwd, moved
    if prog in NODEPM:
        if any(w in NODE_BLOCK for w in words):
            return "block", f"{prog} {words[0]}", cwd, moved
        return ("safe" if any(w in NODE_OK for w in words) or any(a in NODE_OK for a in args) else "unknown"), "", cwd, moved
    if prog in ("docker", "podman"):
        if words[:1] in (["push"], ["login"], ["logout"]) or words[:2] in (["system", "prune"], ["volume", "rm"], ["volume", "prune"], ["image", "prune"]) or ("down" in words and "-v" in args):
            return "block", f"{prog} {' '.join(words[:2])}", cwd, moved
        return "unknown", "", cwd, moved
    if prog in ("curl", "wget"):
        if CURL_WRITE.search(text):
            return "block", f"{prog} that sends data", cwd, moved
        return "unknown", "", cwd, moved
    if prog in ("mysql", "mariadb", "mysqldump", "mysqladmin", "psql", "pg_dump", "mongo", "mongosh", "redis-cli"):
        host = ""
        for i, a in enumerate(args):
            if a in ("-h", "--host") and i + 1 < len(args):
                host = args[i + 1]
            elif a.startswith("--host="):
                host = a[7:]
            elif a.startswith("-h") and len(a) > 2:
                host = a[2:]
        if host and host not in LOCAL_HOSTS:
            return "block", f"{prog} against {host}: THANOS never touches non-local databases", cwd, moved
        if SQL_DESTROY.search(text):
            return "block", "destructive SQL (drop/truncate/delete without where)", cwd, moved
        return "unknown", "", cwd, moved
    if prog == "find" and any(a in ("-delete", "-exec", "-execdir", "-ok", "-fprint", "-fls") for a in args):
        return "unknown", "", cwd, moved
    if prog in READONLY:
        return "safe", "", cwd, moved
    return "unknown", "", cwd, moved


def verdict(command: str, m: dict, cwd: str | None = None, _depth: int = 0) -> tuple[str, str]:
    cwd = os.path.realpath(cwd or os.getcwd())
    deny = [h for h in (m.get("deny_hosts") or []) if isinstance(h, str)]
    if PIPE_TO_SHELL.search(command):
        return "block", "piping a download into a shell"
    try:
        segs = _segments(re.sub(r"\d*>&\d+", " ", command).replace("&>>", ">>").replace("&>", ">"))
    except ValueError:
        return "", ""
    opaque = "$(" in command or "`" in command or "<(" in command or _depth > 2
    kinds, moved = [], False
    for seg in segs:
        kind, why, cwd, moved = _classify(seg, m, cwd, moved, deny)
        if kind == "block":
            return "block", why
        kinds.append(kind)
    if kinds and not opaque and all(k == "safe" for k in kinds):
        return "allow", ""
    return "", ""
