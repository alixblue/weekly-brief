# The Weekly Brief: project plan

**Goal:** stay informed in about 10 minutes a day without hunting for news. One page, about 30 stories from the past week, refreshed daily, from trusted outlets across the political spectrum.

## What the page does (prototype: `site/index.html`)

| Need | How it works |
|---|---|
| No more than ~30 important stories | The script keeps the top 30 by score, with caps so no topic or outlet takes over |
| Grouped by big topic | Aerospace & Aviation, Economy & Industry, Markets & Finance, Environment & Energy, Science & Tech, World & Politics, Culture & Sports (up to 3 light reads) |
| Focus on aeronautics and business | Those topics get a ranking boost (×1.45 and ×1.3) and more slots (11 and 8) |
| Most important = bigger | 3 "top stories" get a large card, the next 9 a wide card, the rest a small one |
| Easy to sort and scroll | Topic filter chips, a "By topic / Most important" switch, sticky toolbar, works on a phone |
| Jargon explained | Highlighted terms open a short definition when tapped (from `glossary.json`) |
| Read inside the page | Tapping a headline opens a reader on the page itself: headline, byline, a summary in one fixed format for every story (What happened · Who's involved · Background · Why it happened · What's next), written only from the public part of the article, how other outlets framed the same story, then Previous / Next. The original link is still there at the bottom if you want the full piece |
| Date, author, source on every story | Shown at the bottom of each card. If an outlet doesn't publish the author, the card says so instead of guessing |
| Not one-sided | The whitelist has 8 left-leaning, 14 center and 9 right-leaning outlets. The script makes sure the weaker side has at least ¾ as many stories as the stronger one. A balance bar shows the mix, and "How other outlets covered it" shows contrasting framings side by side |
| Retro newspaper feel | Blackletter masthead, serif headlines, a bright paper sheet on a darker desk for strong contrast, near-black ink, double rules and column lines, colour accent per topic; dark "night edition" follows your device setting |
| Audio reader | Two modes: "Headlines" (~6 min) or "Full stories" (~20 min) reads every unread brief in order; each story also has its own Listen button. Speed 0.85–1.5×. Uses the browser's built-in voice, so it costs nothing and needs no account |
| The week in 60 seconds | Five bullet takeaways at the top, each linking to its stories (written by Claude daily from the summaries) |
| Dates to watch & follow-ups | Upcoming dates pulled from the stories' "What's next". The script archives every edition in `data/archive/`; when a story continues, it gets an **Update** badge and links to earlier coverage |
| Markets strip | S&P 500, Dow, Nasdaq, Brent, US 10-year yield and EUR/USD with one-week change, from Stooq's free data (prototype uses AP's 9 Oct close) |
| New since last visit | Cards you haven't seen before get a **New** badge and a "New since last visit" filter (remembered in your browser) |
| Opinion / Analysis badges | Columns and reviews are marked **Opinion**; reporting mixed with the writer's view is marked **Analysis** |
| Phone app | Installable from the browser (iPhone: Share → Add to Home Screen; Android: Install app). Opens full screen with its own icon and keeps the last edition for offline reading. Works once hosted on GitHub Pages, not inside the Claude preview |
| Stay motivated | Stories you open are ticked off automatically; a progress bar shows "Read 12 of 30", then "All caught up" |

## How a story is ranked (`pipeline/update.py`)

1. **Fetch** RSS feeds from the whitelist in `sources.json` (wires, newspapers from left to right, aviation trade press, peer-reviewed journals). Keep the last 7 days.
2. **Cluster** the same story across outlets by headline overlap.
3. **Score** = outlet trust weight × (more outlets covering it = more important) × your topic weight × freshness.
4. **Select** the top 30 under caps (max 6 per outlet, per-topic limits), then rebalance left vs right.
5. **Write the briefs (optional)**: with an Anthropic API key, Claude reads each original article and writes the card summary, the in-page brief, notes on how other outlets framed it, and definitions for new jargon, using only what the article says. The article text itself is never stored or republished, only the brief. Without a key, the feed's own summary is used.
6. **Render** the page from the template.

## Roadmap

1. **Now:** review the prototype. Tell me what to change in look, topics, sources or weights.
2. **Host it:** put this folder in a GitHub repository and turn on GitHub Pages. The included workflow (`.github/workflows/daily.yml`) refreshes it every day at 05:00 UTC, free. You get a private-ish URL you can bookmark on your phone. (Alternatives: Netlify or Cloudflare Pages, same idea.)
3. **First live run:** check which feeds fail (the script logs them) and fix their URLs. A few in `sources.json` are best guesses and need that check.
4. **AI briefs:** add an `ANTHROPIC_API_KEY` secret to the repository so the in-page reader has full briefs every day. About 30 briefs a day on a small model costs well under a dollar a month (estimate).
5. **Later ideas:** a "This week in one paragraph" intro at the top; a weekly email or phone notification; a "Why it matters for aerospace" line on business stories; saving stories to a reading list; tuning lean ratings yourself.

## About this prototype (14 Oct 2026)

- The 30 stories are real, from 7–14 Oct 2026, collected by hand because this environment can't download news feeds. Each summary uses only the publicly available part of the article, in the same five-part format.
- Mix this week: 8 stories from left-leaning outlets, 11 from right-leaning, 16 from center (counting "also covered by").
- Lean labels are approximate (AllSides / Ad Fontes Media where rated). Check and edit them in `sources.json`.

## Topic ideas (not added yet; Markets & Finance was added 14 Oct)

Current five stay first. Candidates, most useful first:
1. **Defense & Security**: military aircraft, defence budgets, conflicts. Closest to aerospace.
2. **Technology & AI**: split out of Science, since AI news alone fills a section.
3. **Energy & Commodities**: oil, fuel and metals, split from Environment. Fuel prices hit airlines directly.
4. **Health & Medicine**: drugs, outbreaks, health policy.
5. **Space**: launches and satellites, as a sub-filter of Aerospace.
6. **Culture & Sport**: two or three light reads a week.
A region filter (Europe / Asia-Pacific / Americas / Middle East & Africa) could sit alongside topics instead of being one.

## Canva and NotebookLM

Neither is needed. The page is designed in code, so it updates itself; a Canva design would have to be rebuilt by hand each day. Canva is still useful if you want to design a logo, colour palette or header image for me to plug in. NotebookLM is good for a different job: dropping a week of articles in and asking questions or getting an audio overview. No extra skills or connectors are required for this project; a GitHub connection is the only thing needed for hosting.
