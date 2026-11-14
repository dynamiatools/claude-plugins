---
name: issues
description: Closes or updates GitHub issues after work was shipped, one by one against what the code really does, with a comment that links the PR. Use when the user asks to close issues, update them, or leave progress comments after a merge. Never closes an issue that is only partly done.
argument-hint: "[issue numbers]"
allowed-tools: Bash(gh issue view:*) Bash(gh issue list:*) Bash(gh pr view:*)
---

# dynamia:issues

Closing an issue is visible to others, so it is done only when the user asks, and only for what is true. The rule: **close what is fully done, comment progress on what is partly done, leave the rest alone.**

## Steps

1. **Collect the issues**: `$ARGUMENTS`, or the ones the work referenced (`#123` in commits and PR titles: `git log <base>..HEAD --format=%s`). Read each with `gh issue view <n> --json title,body,state,labels,comments`. Never guess an issue's content.
2. **Check each against the code, not against memory.** Compare its acceptance criteria with the merged change (read the diff or the tests). For every issue decide one of:
   - **Done**: every criterion is met and verified (a test or a command you can name).
   - **Partial**: part is done; list what is not.
   - **Not touched**: say nothing.
   Parts that depend on another team or system (an ERP field, a decision) are *not done*, even if the POS side is.
3. **Show the user the table** (number, title, verdict, one-line reason) and ask once, with `AskUserQuestion`, only if a verdict is arguable. Otherwise go on.
4. **Write the comments**, in the issue's language, short and factual:
   - Done: `gh issue close <n> --reason completed --comment "Done in #<pr>: <what was delivered, and any known limit>"`.
   - Partial: `gh issue comment <n> --body "Progress in #<pr>: <done>. Still open: <what is missing and why>"`. Leave it open.
   Link the PR number, name the limit instead of hiding it, and never close an issue as `completed` that you did not verify.
5. **Epics and trackers**: if a parent issue has a checklist, tick only the items you just closed; do not close the epic.
6. **Report** the list: closed, commented, untouched. End with what you did not verify.

## Notes
- Inside a THANOS mission `gh` writes are blocked (read-only lookups are allowed): do this after the mission, with the user.
- A repo's own CLAUDE.md can add rules (native issue types, sub-issues, priority fields): follow it.
