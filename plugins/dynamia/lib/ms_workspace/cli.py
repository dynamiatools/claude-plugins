"""Command dispatch for ms-workspace."""
from __future__ import annotations

import sys

from .core import MsError, Workspace

USAGE = """\
ms-workspace: mechanical helper for the multi-repo batch workflow.
Reads <project>/.dynamia/workspace.toml (created by the dynamia:workspace-init skill).
Deterministic on purpose: skills and hooks call it so the model does not
have to spend tokens on git/test plumbing.

Usage:
  ms-workspace batch new <name> [repo...]    create a batch (one worktree per repo, branch int/<name>)
  ms-workspace affected                      JSON: changed repos/modules and their dependents
  ms-workspace agent new <batch> <task> [repo...]   isolated worktree per agent (branch agent/<batch>/<task>)
  ms-workspace open <batch> [--ide code|idea] [--repo R] [--agent TASK] [--dry-run]   open the batch's worktrees in VS Code or IntelliJ (git untouched)
  ms-workspace env [batch] [--setup] [--trust]   copy ignored files (.worktreeinclude, env_files) into the batch worktrees
  ms-workspace test t0                       test what changed in the current repo (add --no-cache to force a run)
  ms-workspace test t1 [batch]               affected + critical modules for every changed repo of the batch
  ms-workspace test t2 [batch]               end-to-end command from [e2e] in workspace.toml
  ms-workspace integrate <batch> [--dry-run] merge agent branches into int/<batch> (conflicts detected first)
  ms-workspace ship <batch> [--yes] [--pr] [--skip-e2e]   sync with base, test, push (plan only without --yes); --pr opens a PR instead of pushing to base
  ms-workspace plan <batch>                  same as `ship` without --yes: shows what would be sent, changes nothing
  ms-workspace undo <batch> [--yes]          revert the last ship: adds a commit restoring the old tree (never force-pushes)
  ms-workspace clean [<batch>] [--force]     list batches, or remove one that is already merged
  ms-workspace log [-n N] [--day YYYY-MM-DD] [--action A]   show recent actions
  ms-workspace context                       ~15-line briefing (for a SessionStart hook)
  ms-workspace status [--fetch]              one line per repo: branch, ahead/behind base, dirty, batches
  ms-workspace claude-md [--print]           (re)generate <project>/CLAUDE.md; only the managed block is touched; an existing file needs --append
  ms-workspace usage [--check] [--need PCT] [--json|--line]   plan usage: 5h session and 7d week, pace, verdict
  ms-workspace images [list|capture|backfill]   archive images pasted in chat into <workspace>/images/
  ms-workspace memory [add|list|search|show|forget]   small local notes: decisions, lessons, gotchas, handoffs
  ms-workspace insights [--days N] [--json]  what the log says: slow/flaky tests, time and plan usage per batch
  ms-workspace tokens [--days N] [--json]    token audit of the Claude Code sessions run inside this workspace
  ms-workspace dev-env [list|add NAME=value|rm NAME] [--repo R]   development variables in workspace.toml, applied to test/e2e/setup commands
  ms-workspace project [dir]                 JSON: inside a git repo? workspace layout? CLAUDE.md the repo's own?
  ms-workspace exclude [dir]                 add .dynamia/ to the repo's .git/info/exclude (local, nothing tracked)
  ms-workspace migrate [--yes]               move an older layout into .dynamia/, or clones left inside .dynamia/workspace/ out to the project (dry run without --yes)
  ms-workspace setup-hooks [--dry-run] [--remove] [--project]   merge the ms-* hooks and status line into settings.json
  ms-workspace budget [--top N] [--json]     what every session loads before you type (CLAUDE.md, skills, agents, memory), in tokens
  ms-workspace readguard / outguard          token-saving hooks: warn on re-reading an unchanged file; shorten huge Bash output
  ms-workspace http run <file> [--env E] ...  API checks from requests/*.http.toml: assertions, captured variables, a log of every exchange
  ms-workspace http list|history|show|diff|bench   see the files, past runs, one exchange, what changed between runs, latency percentiles
  ms-workspace mock start|stop|status|url|list|requests|assert   local mock server for third-party APIs (mocks/*.mock.toml) that records every call
  ms-workspace docker status|logs|stats|disk|health|ports|env|wait|clean   compact Docker views; only `clean --yes` changes anything
  ms-workspace sys [--tools] [--json]        OS, CPU, memory, disk, network in a few lines, with hints when something looks wrong
  ms-workspace ps [tree|find|ports|leftovers|kill]   processes: heavy ones, who holds a port, what was left running, guarded kill
  ms-workspace gate [batch] [--json]         scan what would be sent for secrets, merge markers, huge files and debug leftovers
  ms-workspace junit [paths] [--since MIN] [--top N]   summarize JUnit/Surefire/Gradle/vitest/pytest XML reports: failing tests, message, first project frame
  ms-workspace modules [deps|rdeps <m>|closure|check]   Maven reactor graph: dependents, exact -pl list for a change, cycles, [[arch.rule]] checks
  ms-workspace recall <words...> [--kind K] [-n N]   full-text search over past sessions, memory notes and the log ("where did we decide X?")
  ms-workspace handoff [--batch B] [--print] | --hook   write the state needed to resume a batch (a hook does it before compaction and at the end)
  ms-workspace promote [repo] [--to qa|main] [--yes] [--direct]   open a PR from the base branch to a release branch (plan only without --yes)
  ms-workspace release status|notes [repo]   what waits to be promoted from the base branch to qa/main, grouped by commit type, and release notes
  ms-workspace notify <message> [--title T] | --test | --hook   send a notification (ntfy, webhook or local command from [notify]); also a Notification hook
  ms-workspace doctor                        check tools, versions, resources and workspace.toml
  ms-workspace guard                         PreToolUse hook: blocks git push / gh pr create|merge in batch worktrees

Workspace discovery: $MS_WORKSPACE, else the nearest parent holding .dynamia/workspace.toml (or, older layout, workspace.toml).
"""


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except AttributeError:
            pass
    cmd, args = (argv[0], argv[1:]) if argv else ("", [])
    try:
        return _dispatch(cmd, args)
    except MsError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    except BrokenPipeError:
        return 0
    except KeyboardInterrupt:
        return 130


def _dispatch(cmd: str, args: list[str]) -> int:
    if cmd in ("", "-h", "--help", "help"):
        print(USAGE, end="")
        return 0
    # Commands that must work (or stay silent) without a workspace.
    if cmd == "guard":
        from .guard import cmd_guard
        return cmd_guard()
    if cmd == "images":
        from .images import cmd_images
        return cmd_images(args)
    if cmd == "usage":
        from .usage import cmd_usage
        return cmd_usage(Workspace.load(required=False), args)
    if cmd == "context":
        from .overview import cmd_context
        return cmd_context(Workspace.load(required=False))
    if cmd == "readguard":
        from .hooks import cmd_readguard
        return cmd_readguard(args)
    if cmd == "outguard":
        from .hooks import cmd_outguard
        return cmd_outguard()
    if cmd == "notify":
        from .notify import cmd_notify
        return cmd_notify(Workspace.load(required=False), args)
    if cmd == "handoff":
        from .handoff import cmd_handoff
        return cmd_handoff(Workspace.load(required=False), args)
    if cmd == "modules":
        from .modules import cmd_modules
        return cmd_modules(Workspace.load(required=False), args)
    if cmd == "junit":
        from .junit import cmd_junit
        return cmd_junit(Workspace.load(required=False), args)
    if cmd == "gate":
        from .gate import cmd_gate
        return cmd_gate(Workspace.load(required=False), args)
    if cmd == "open":
        from .ide import cmd_open
        return cmd_open(Workspace.load(), args)
    if cmd == "docker":
        from .dockertools import cmd_docker
        return cmd_docker(Workspace.load(required=False), args)
    if cmd == "sys":
        from .sysinfo import cmd_sys
        return cmd_sys(Workspace.load(required=False), args)
    if cmd == "ps":
        from .procs import cmd_ps
        return cmd_ps(Workspace.load(required=False), args)
    if cmd == "mock":
        from .mock import cmd_mock
        return cmd_mock(Workspace.load(required=False), args)
    if cmd == "http":
        from .apitest import cmd_http
        return cmd_http(Workspace.load(required=False), args)
    if cmd == "budget":
        from .budget import cmd_budget
        return cmd_budget(Workspace.load(required=False), args)
    if cmd in ("project", "exclude", "migrate"):
        from . import project
        return {"project": project.cmd_project, "exclude": project.cmd_exclude, "migrate": project.cmd_migrate}[cmd](args)
    if cmd == "dev-env":
        from .devenv import cmd_dev_env
        return cmd_dev_env(Workspace.load(), args)
    if cmd == "setup-hooks":
        from .setup import cmd_setup_hooks
        return cmd_setup_hooks(args)
    if cmd == "doctor":
        from .overview import cmd_doctor
        return cmd_doctor(Workspace.load(required=False))

    from . import batches, claude_md, insights, memory, overview, runner, tokens
    table = {
        "batch": batches.cmd_batch, "agent": batches.cmd_agent, "affected": batches.cmd_affected,
        "env": batches.cmd_env, "integrate": batches.cmd_integrate, "ship": batches.cmd_ship,
        "clean": batches.cmd_clean, "undo": batches.cmd_undo, "plan": lambda ws, a: batches.cmd_ship(ws, [x for i, x in enumerate(a) if i == 0 or x == "--pr" or (a[0] == "--branch" and i == 1 and not x.startswith("-"))]), "test": runner.cmd_test, "log": overview.cmd_log,
        "status": overview.cmd_status, "claude-md": claude_md.cmd_claude_md,
        "memory": memory.cmd_memory, "promote": lambda ws, a: __import__("ms_workspace.promote", fromlist=["x"]).cmd_promote(ws, a), "release": lambda ws, a: __import__("ms_workspace.release", fromlist=["x"]).cmd_release(ws, a), "recall": lambda ws, a: __import__("ms_workspace.recall", fromlist=["x"]).cmd_recall(ws, a), "insights": insights.cmd_insights, "tokens": tokens.cmd_tokens,
    }
    if cmd not in table:
        print(f"ERROR: unknown command: {cmd}", file=sys.stderr)
        return 1
    return table[cmd](Workspace.load(), args)
