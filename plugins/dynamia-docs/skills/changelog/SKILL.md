---
name: changelog
description: Writes changelogs and release notes with Keep a Changelog, Semantic Versioning and Conventional Commits - picks the next version, groups changes for humans, flags breaking changes and drafts notes from git history. Use when preparing a release, writing or updating CHANGELOG.md, deciding the next version number, writing commit messages or announcing breaking changes. Triggers on "prepara el changelog", "notas de la versión".
argument-hint: "[version or range]"
---

# dynamia-docs:changelog

Based on Keep a Changelog 1.1.0, Semantic Versioning 2.0.0 and Conventional Commits 1.0.0 (read from their sites on 2026-10-23). Follow the repository's own commit and versioning convention first: this marketplace bumps plugin versions by its own rule (patch for fixes and wording, minor for new skills or hooks while below 1.0) and the Dynamia framework uses `YY.MM.N`; SemVer applies where the project declares it.

## Changelog (for humans)
- File `CHANGELOG.md`, newest first, one section per version with the **release date in ISO 8601** (`## [1.2.0] - 2026-10-23`), and an `## [Unreleased]` section on top for upcoming changes. Mention whether the project follows SemVer.
- Group entries by type: **Added**, **Changed**, **Deprecated**, **Removed**, **Fixed**, **Security**. Write for users: what changed for them and what to do (not commit hashes, not internal refactors).
- Always list **deprecations, removals and breaking changes** with the migration path. A partial changelog misleads.
- Mark pulled releases `[YANKED]`. Link version headings to compare URLs at the bottom of the file.
- Don't paste the git log: it is noisy and not written for readers.

## Choosing the next version (SemVer 2.0.0)
`MAJOR.MINOR.PATCH`: **MAJOR** for incompatible public API changes, **MINOR** for backward-compatible functionality (also when deprecating a public feature), **PATCH** for backward-compatible fixes. Never modify a released version. `0.y.z` is initial development: anything may change. Pre-release `1.0.0-rc.1` sorts below `1.0.0`; build metadata is ignored in precedence. The project must **declare its public API**; "breaking" is judged against it. Deprecate in a minor release before removing in a major.

## Commit messages (Conventional Commits 1.0.0)
`<type>[optional scope]: <description>`, optional body and footers after blank lines. `fix` (PATCH), `feat` (MINOR), other types (`build`, `chore`, `ci`, `docs`, `style`, `refactor`, `perf`, `test`) have no implicit version effect. **Breaking change**: `!` before the colon (`feat(api)!: ...`) or a `BREAKING CHANGE:` footer (uppercase); it implies MAJOR. Imperative mood, one logical change per commit, a body that says **why**. If the project has its own style, follow it (this repo: imperative subject plus a short body).

## Drafting release notes from history
1. Find the last release tag and list changes since (`git log <tag>..HEAD`, merged PRs, issue links).
2. Classify into the types above, merge duplicates, drop noise (formatting, CI-only), turn commit text into user-facing sentences.
3. Highlight breaking changes first, with before/after and migration steps; then features; then fixes; then security.
4. Propose the next version from the highest-impact change (and say the reason), and let the maintainer confirm.
5. Add the compare link; update docs mentioned (`dynamia-docs:readme`, `api-docs`).

## Rules
- Facts only from history and diffs; don't invent features, CVE ids or benchmarks. Unknown details: "to confirm".
- Security fixes: say what is fixed and who is affected without handing out exploit steps; follow the project's disclosure process.
- One source: if the project generates release notes in CI, edit the template, not each release by hand.

## Optional pointers
In a Dynamia multi-repo workspace the `dynamia` plugin has `/dynamia:release` (what waits to be promoted and release notes draft) and a `summarizer` agent; if installed (listed among skills/agents) they can build the raw list, otherwise suggest `/plugin install dynamia@dynamia-tools` once.

End with one line: version proposed and why, range covered, what needs the maintainer's confirmation.
