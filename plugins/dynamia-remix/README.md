# dynamia-remix

Remix an app you admire into your own product, clean-room. It studies what an app does, never what it owns: no code, assets, logo, copy or content. Six skills that hand work to each other through a `remix/` folder in your project. No hooks.

```
recon -> plan -> build -> parity -> voice -> brand
```

| Skill | Use it to |
|---|---|
| `/dynamia-remix:recon` | Map screens, flows, data model and a feature matrix from public sources and your own account |
| `/dynamia-remix:plan` | Pick the stack, write the schema and API, order the build |
| `/dynamia-remix:build` | Rebuild screen by screen, all states, fresh code and words |
| `/dynamia-remix:parity` | Score it against the original and list what is missing |
| `/dynamia-remix:voice` | Rank what the original's users hate, with linked quotes, and find your angle |
| `/dynamia-remix:brand` | Name it, rebrand it, sweep the code until nothing of the original is left |

Three standard-library Python scripts (Python 3.11+, no network): `remix-parity`, `remix-voice`, `remix-sweep`, in `bin/`. The skills call them.

## Rules the skills enforce

- Public sources and your own account only. No scraping behind logins, no paywall tricks, no reading the app's bundles or network calls.
- Reviews are never invented. Every quote is verbatim with a link.
- Not shippable until the sweep is clean. Trademark checks are screening only; talk to a lawyer before money is at stake. This is not legal advice.

## Related plugins (optional)

`dynamia-ui` for the design system and landing page, `dynamia-test` for tests, `dynamia` for shipping. Install with `/plugin install <name>@dynamia-tools`.

Install:

```
/plugin marketplace add dynamiatools/claude-plugins
/plugin install dynamia-remix@dynamia-tools
```

Tests: `python3 -m unittest discover -s tests`. Adapted from [replica-skill](https://github.com/Jakeschincariol/replica-skill) (MIT), see `NOTICE`.
