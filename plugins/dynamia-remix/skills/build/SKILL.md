---
name: build
description: Rebuilds the app screen by screen from the recon map, shell first, then the core flow as a vertical slice, then every screen with all its states, keeping the feature matrix current. Writes everything fresh. Use after /dynamia-remix:plan, or when the user says "build the remix", "build screen S07" or "implement the booking page".
---

# build

Reads `remix/recon.md`, `remix/plan.md`; updates the `clone` column of `remix/features.csv` and keeps `remix/build-log.md`.

## Rules

- **Clean room.** Every line is written here from the recon map. Never paste the original's HTML, CSS, JS, SVGs or images, never load anything from its domain or CDN, never "view source and adapt".
- **Your words.** Labels, empty states and emails are written fresh. Same behavior is parity, same sentence is copying.
- **Design tokens, no raw values.** If a value is missing, add it to the tokens. To extract or create the design system, use `/dynamia-ui:design-system` if `dynamia-ui` is installed (otherwise suggest `/plugin install dynamia-ui@dynamia-tools` once); a small token file of your own also works.

## Steps

1. **Shell.** Routes for every screen (stubs are fine), layout, tokens, seed data. Commit.
2. **Vertical slice.** The core loop end to end before anything else. Without a backend yet, use a fake data layer with the real function signatures so swapping it changes no screen code.
3. **Screen by screen**, in the order of `plan.md`. For each: read its recon row, look at the reference screenshot for layout and hierarchy (not pixels), build it with real data, and cover every state (empty, loading, filled, error, no permission, long content, 390px and 1440px wide). Semantic HTML, labeled inputs, keyboard reachable, visible focus. Set the matching `features.csv` rows to `yes` or `partial` with a note. One commit per screen: `build: S07 booking page`.
4. **Build log.** One line per screen: done or partial, what is missing, what was harder than expected. If a feature is bigger than it looked, say so in the log and in chat. Never quietly ship half of it.

When stuck on how something works, go back to the original as a user (its help article, a public walkthrough, the user's own account) and build your own version of the behavior. Never its code or network calls.

## Output

Screens done of total, must-haves done of total, what is next: `/dynamia-remix:parity`. For tests, use `dynamia-test:*` if installed.
