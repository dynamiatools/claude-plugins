---
name: flash
description: Builds a quick prototype alone, with no questions and no ceremony, in the current branch, using Haiku helpers for the code and one final Opus pass for explosions, security risks and a production architecture recommendation. Never commits or pushes unless told. Use only when the user asks for FLASH, a quick prototype, a spike, "hazlo rápido" or "un prototipo".
argument-hint: "<what to build> [--commit]"
---

# dynamia:flash

> ⚡ **FLASH.** Fast, small, working. Production comes later.

Print that line when you start. The goal is a prototype that runs, not a product. Speed beats polish, but a prototype that explodes or leaks is not a prototype, so one Opus pass at the end checks that.

## Rules
- **No question round.** Decide with sensible defaults and keep a list of them for the report. Ask only if the goal cannot be understood at all, and then one short question.
- **Current branch, current checkout.** No worktree, no batch, no new branch. **No commit and no push** unless the user said so in the request (`--commit` or "commitea"); then one local commit at the end, never a push. If the working tree already has changes, note it and do not touch those files.
- **Smallest thing that works.** Before writing: does it already exist in the repo, the standard library, the platform, an installed dependency? Use it. No abstractions for a second use that does not exist, no config, no layers, no generalization, no new dependency unless it removes real work. Hard-code what a prototype can hard-code, and mark it `// shortcut: <when to revisit>`.
- **Use the skills that apply, do not read about them.** Look at the skills list once and invoke those that match the stack or task (for example `dynamia-platform:backend`, `dynamia-ui:design-system`, `dynamia-java:spring-boot`, `dynamia-kotlin:idioms`, `dynamia-colombia:*`) instead of working from memory. Skip any that does not clearly apply.
- **Stay in the repo and out of the world.** Never touch anything outside the project, never deploy, never call production or real third-party services with real credentials, never put a secret in a file. Use local data, fakes and `.env.example` placeholders.
- **Do not repair what you were not asked to build.** No refactors of old code, no extra tests beyond one smoke check.

## Steps
1. **Read just enough.** The repo's CLAUDE.md or README and the files the change touches. For a wide search use `dynamia:scout` (Haiku) instead of reading many files.
2. **Plan in 3 to 7 lines**, no file. Each line is one small piece that can be built and run alone. Name the one command that proves the prototype works (a run, a `curl`, a test, a build).
3. **Build with Haiku.** Give each independent piece to `dynamia:flash-builder` (Haiku) with the exact files, the behavior, the stack conventions and the done check. Launch independent pieces in parallel in one message; do dependent ones in order. Do tiny pieces (a few lines) yourself rather than pay for an agent. Their answer is a lead: open what they changed before relying on it.
4. **Run it.** Execute the proving command. If it fails, give the output to `dynamia:test-triage` for a lead, fix, run again. Two failed attempts at the same thing: simplify the approach or cut that piece and say so in the report. Do not loop.
5. **Opus pass, once.** Launch `dynamia:flash-auditor` (Opus, read-only) in the foreground with the goal, the files changed (`git status --short` and `git diff --stat`) and the run command. It returns at most 30 lines: what can explode, security risks, and what architecture to use for a production version. Fix only the items it marks `fix-now` (things that would crash, lose data or leak a secret even in a demo); leave the rest for the report. Never launch it a second time.
6. **Commit only if asked**, one local commit; otherwise leave the changes in the working tree. Never push.
7. **Report**, short, in the user's language, with the marks 🟢 works (command and result), 🔴 broken, 🟡 not verified or shortcut taken, 🟣 decision made:
   - what was built and how to run it;
   - the decisions and shortcuts;
   - the auditor's `explosions`, `security` and `production` sections, trimmed;
   - the last line: what was not verified and what must change before this leaves prototype stage.

## Notes
- Budget: if `ms-workspace usage --check` exists and warns, tell the user the numbers in one line and go on only if the prototype is small.
- For long, many-repo or risky work use `/dynamia:thanos` instead; FLASH is for a spike you can read in five minutes.
