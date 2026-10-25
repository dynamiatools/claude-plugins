---
name: brand
description: Names and rebrands the remix so it is the user's own, with name candidates and the checks to run, a new palette, a voice guide, and remix-sweep to find anything of the original left in the code. Use when the user asks to name the app, rebrand, make it theirs, or check for leftovers, and always before launching.
---

# brand

Nothing launches under the original's identity. This is the line between a copy and a product.

## Steps

1. **Name.** Read the angle in `remix/fixes.md`. Generate about 20 candidates across styles (descriptive, compound, invented, metaphor, verb), cut to 5. Not confusingly similar to the original or to others in the category in sound, look or meaning; no puns on its name. Short, spellable after hearing it once, no bad meaning in big languages.
2. **Checks, run and not assumed.** Per candidate: US trademark (tmsearch.uspto.gov), EU (EUIPO eSearch or TMview), WIPO Global Brand Database, domain (`whois`), App Store and Google Play search, social handles, web search. Write each as `to run` or the result with its date. Never write "available" for a check nobody ran. These are screening checks, not legal clearance: before spending money on the name, a trademark lawyer should search properly.
3. **Palette and voice.** New colors from a different hue family than the original's, written into the same token roles the build uses, with WCAG AA contrast on text. A few lines of voice: how it talks, words it uses, words it avoids. A logo brief (an idea and constraints, not an image).
4. **Brand file.** Write `remix/brand.md` and `remix/brand.json`:

```json
{"avoid": ["Original Name", "Its Company"], "domains": ["original.com"], "colors": ["#006bff"]}
```

5. **Sweep until clean.** Rename in the code, then run:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/bin/remix-sweep . --config remix/brand.json
```

It finds the original's names, domains and colors, including inside identifiers like `OriginalAppEmbed`, and exits 1 until clean. Fix every hit; never silence the tool. Also check that app store listings and ads do not use the original's name.

Not clean means not ready to ship. Publishing is the user's call: `/dynamia:ship` if `dynamia` is installed.
