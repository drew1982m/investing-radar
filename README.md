# Traction Radar

A free, self-populating dashboard that surfaces things gaining early real-world
traction — the Afterpay-at-$4 pattern — so your judgment gets more shots on goal.

It is a **funnel filler, not an oracle.** Most of what it flags is noise. That's
by design. The value is (1) aggregating public early-traction signals to one place
you check, and (2) the thesis log, which forces you to write down *why* before you
act and tells you later whether your read was good or just felt good.

## What it watches (all free, no API keys)

- **Apple App Store rank velocity** — apps climbing fast in a category/country
  (incl. Australia, where Afterpay first climbed). The strongest consumer signal.
- **Google Trends breakouts** — search terms inflecting over 7 days.
- **Reddit engagement velocity** — posts gaining traction in chosen subreddits.
- **GitHub star velocity** — young repos gaining stars fast (dev-tooling/infra).

## How it runs

A GitHub Actions workflow runs the scraper once a day (and whenever you trigger it
manually), commits the results as `docs/feed.json`, and GitHub Pages serves the
dashboard at a URL you bookmark. No server, no cost, nothing running on your machine.

**Velocity needs history.** The first run has nothing to compare against, so
rank-climb flags start appearing on the *second* run. New-to-chart, GitHub, Reddit
and Trends signals work from run one.

## One-time setup (~15 min)

1. **Create a new repository** on GitHub (public is simplest for free Pages).
   Name it whatever you like, e.g. `traction-radar`.
2. **Upload these files** — drag the whole folder contents into the repo (via
   GitHub's "Add file → Upload files"), keeping the structure:
   ```
   .github/workflows/radar.yml
   scripts/radar.py
   docs/index.html
   requirements.txt
   README.md
   .gitignore
   ```
3. **Enable Pages:** repo **Settings → Pages →** Source: *Deploy from a branch*,
   Branch: `main`, Folder: `/docs`. Save. After a minute your dashboard is live at
   `https://<your-username>.github.io/<repo>/`.
4. **Allow Actions to commit:** repo **Settings → Actions → General →** Workflow
   permissions → select *Read and write permissions*. Save. (The workflow commits
   the updated feed back to the repo.)
5. **First run:** go to the **Actions** tab → *Traction Radar* → *Run workflow*.
   Watch it go green. Refresh your Pages URL — the feed appears.
6. **Run it once more** the next day (or manually) so velocity has history to
   compare and app-climb flags start showing.

## Tuning what it watches

Everything is in `scripts/radar.py` near the top:

- `APPSTORE_TARGETS` — add/remove country + category rows. Category IDs are in a
  comment there (Finance 6015, Shopping 6024, etc.).
- `TRENDS_TERMS` — the search terms checked for breakout.
- `REDDIT_SUBS` — subreddits to watch.
- `GITHUB_TOPICS` — topics to scan.

Thresholds (what counts as a "mover") are also in that file — raise them if the
feed is too noisy, lower them if it's too quiet.

## Running locally instead / as well

```
pip install -r requirements.txt
python scripts/radar.py          # writes docs/feed.json
# then open docs/index.html in a browser
```

## Honest limitations

- App Store charts cap at the top 200 per category, so a truly pre-launch product
  won't appear — but something *climbing* will, which is the pattern you want.
- Reddit and Google Trends occasionally block or rate-limit automated requests.
  The scraper is built to skip a failing source and keep going rather than crash;
  if one goes quiet for a while, that's usually why.
- Theses are stored in your browser's local storage — **per device, not synced.**
  If you want them shared across devices, that's the point where a tiny backend
  (or a paid tier) earns its keep. Not needed to start.

## Tradability triage (respecting a public-markets-only constraint)

The free sources carry no ticker data — an app-store entry is just an app name.
Rather than filter the *feed* (which would throw away the early signal, since the
whole edge is spotting a product before it's obviously tied to a stock), tradability
is captured at the **thesis** step, by you:

- When you log a thesis, pick **Public / Public parent / Private / Unknown** and
  add the ticker if you know it. The 30-second "who owns this, are they public"
  lookup is itself part of the edge — most people skip it.
- The thesis log has a **filter** so you can view *tradable only* (public + public
  parent) and ignore anything you can't buy.
- "Public parent" is often the most interesting case: a small hot product inside a
  big-cap can be an early tell that the market hasn't priced.

## The discipline that makes this worth doing

Log a thesis before you act. Write the disconfirming case — what would prove you
wrong. Review your hit rate over time. If the radar ever makes you feel like you
have an edge just because you're looking at data, that feeling is the thing to
distrust. The signal is public; the judgment is yours, and judgment is the part
worth measuring.
