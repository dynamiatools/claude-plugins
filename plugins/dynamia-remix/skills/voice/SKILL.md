---
name: voice
description: Reads what the original app's real users complain about in public reviews and turns it into a ranked fix list and a positioning angle, with remix-voice. Every quote is verbatim and linked. Use when the user asks what people hate about an app, how to make theirs better, how to position it, or whether it is worth remixing.
---

# voice

A straight copy has no reason to exist. This finds the reason, in the users' own words. It also works before any build, to decide if an app is worth remixing.

## Rules

- **Never fabricate.** No invented reviews, quotes, ratings or counts. If a source cannot be reached, say so. If there are 14 reviews, say 14.
- **Verbatim and linked.** Copy text exactly, with the review's URL. `remix-voice` drops any row without a link.
- **Reading, not scraping.** Read review pages like a person and copy rows in. Official public feeds and APIs within their terms are fine (Apple's customer reviews RSS feed, the Hacker News Algolia API). No scraping libraries against sites whose terms forbid it.
- **No fake reviews, ever**, for your app or against theirs. Reviewers are research, not testimonials: their words never go on a landing page.

## Steps

1. **Collect** 100+ reviews from at least three sources, recent first: App Store, Google Play, G2, Capterra, Trustpilot, Reddit ("X alternative", "switched from X"), Hacker News, the original's public feature-request board. Read the 3 and 4 star ones: "love it, but..." hides the best fixes. Rows go in `remix/reviews.csv` as `source,url,date,rating,text`.
2. **Rank:**

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/bin/remix-voice remix/reviews.csv --out remix/voice.md
```

Themes with under 3 reviews or one source are marked thin; do not build a strategy on them. For another category, pass `--themes themes.json` (`{"theme": ["keyword", ...]}`).
3. **Fix plan.** For each solid theme: what to change in the remix, effort S/M/L, and the evidence (count, sources, links). Check the original's changelog so you do not "fix" what is already fixed. Write `remix/fixes.md`.
4. **Angle.** One sentence: who the remix is for and what it does that the original does not. It must come from the evidence above, not from taste.

Next: `/dynamia-remix:brand`.
