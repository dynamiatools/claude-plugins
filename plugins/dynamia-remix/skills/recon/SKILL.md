---
name: recon
description: Maps an app you want to remix, from public pages, docs, store listings and the user's own account, into a recon map with screens, flows, data model and a feature matrix. First step of the remix workflow. Use when the user says "remix this app", "clone X", "map out X", "what screens does X have", or pastes an app URL they want to rebuild in their own way.
---

# recon

Everything else builds from what this writes. Output goes in the user's project:

```
remix/recon.md        screens (S01..), flows (F01..), components, inferred data model, size
remix/features.csv    the feature matrix (start from features.csv in this folder)
remix/screens/        reference screenshots. Reference only, never shipped.
```

## Rules

- **Clean room.** Study what the app does and how users move through it. Never take what it owns: code, assets, logo, copy, content, private APIs.
- **Public sources and the user's own account only.** Never log into someone else's account, never get past a paywall, never crawl or bulk download. Read at human speed.
- **Do not read the app's JavaScript bundles, decompile it, or log its network calls** to copy endpoints. Public API docs are fine.
- **Check the terms.** If the user's account forbids building a competing product, say so and use public sources only.

## Steps

1. **Scope.** Ask which app and platform, which slice (default: the core loop users pay for, never "all of Notion"), and who it is for. Propose answers and get a yes.
2. **Sources table**, a URL on every row: help center (most complete feature list), pricing page (what they gate), changelog, store listing, public walkthroughs, API docs, the user's own account.
3. **Screens.** One row each, stable IDs: `ID | screen | how you get there | purpose | components | states seen`. Record empty, loading, error, no-permission and mobile states, or they will not get built.
4. **Flows.** `F01 goal: S07 -> S08 -> S09`, plus edge cases. Count the clicks on the happy path.
5. **Data model.** Entities, fields, relations, each with its evidence and a confidence. Mark guesses as guesses.
6. **Features.** Fill `features.csv` (columns: feature, area, priority must/should/could, original yes/no, clone, notes). `clone` starts at `no`.
7. **Cannot be remixed.** Add `skip` rows with the reason: licensed content, the user network, data the app owns, partner deals, regulated licences.
8. **Size it.** Screens, flows, entities, hard parts (realtime, sync, payments, integrations, offline). S weekend, M weeks, L quarter, XL rescope. No promise of a perfect copy.

## Output

Files above, then five lines: the core loop, screen and flow counts, the three hardest parts, what is out of scope, next step `/dynamia-remix:plan`.
