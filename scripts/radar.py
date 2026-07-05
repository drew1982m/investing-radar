#!/usr/bin/env python3
"""
Traction Radar — free-tier early-signal scraper.

Pulls publicly available signals that indicate something is gaining traction,
computes velocity against previously stored snapshots, and writes a ranked
JSON feed the dashboard reads. Designed to run on GitHub Actions on a schedule,
but also runs fine locally (python scripts/radar.py).

Philosophy: this is a FUNNEL FILLER, not an oracle. It widens what crosses your
desk so your judgment gets more shots on goal. Most flags are false positives by
design. The thesis log (docs/theses.json) is where discipline lives.

Sources (all free, all server-side friendly — no API keys required):
  - Apple App Store RSS top charts (per country + category), velocity of rank change
  - Google Trends breakout terms via pytrends (optional; degrades gracefully)
  - Reddit subreddit post velocity via public JSON
  - GitHub trending-ish via search API (stars gained recently)

No source is allowed to crash the run. Each is wrapped; failures are logged and
the run continues with whatever succeeded.
"""

import json
import os
import sys
import time
import datetime as dt
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DOCS = ROOT / "docs"
SNAP_DIR = DATA / "snapshots"
SNAP_DIR.mkdir(parents=True, exist_ok=True)
DOCS.mkdir(parents=True, exist_ok=True)

UTCNOW = dt.datetime.now(dt.timezone.utc)
TODAY = UTCNOW.strftime("%Y-%m-%d")
UA = "traction-radar/1.0 (personal research; contact: you@example.com)"

# ---- Config: what we watch ------------------------------------------------
# App Store: (country, feed_type, category_id, human_label)
# category ids: 6015 Finance, 6024 Shopping, 6002 Utilities, 6007 Productivity,
# 6005 Social Networking, 6023 Food & Drink. Countries chosen to catch things
# rising in one market before they go global (au = Australia, the Afterpay case).
APPSTORE_TARGETS = [
    ("au", "topfreeapplications", 6015, "AU / Finance (free)"),
    ("au", "topfreeapplications", 6024, "AU / Shopping (free)"),
    ("us", "topfreeapplications", 6015, "US / Finance (free)"),
    ("us", "topfreeapplications", 6024, "US / Shopping (free)"),
    ("gb", "topfreeapplications", 6015, "GB / Finance (free)"),
    ("us", "topfreeapplications", 6023, "US / Food & Drink (free)"),
]
APPSTORE_LIMIT = 100  # Apple allows up to 200; 100 keeps noise down

# Google Trends seed terms to check for breakout. Kept small — pytrends is rate
# limited. Edit freely.
TRENDS_TERMS = [
    "buy now pay later", "stablecoin", "AI agent", "weight loss drug",
]
TRENDS_GEO = ""  # "" = worldwide; or "US", "AU", etc.

# Reddit: subreddits where consumer/fintech/tech traction shows up early.
REDDIT_SUBS = ["fintech", "startups", "apps", "SideProject"]

# GitHub: topics to scan for fast-rising repos.
GITHUB_TOPICS = ["ai-agent", "fintech", "developer-tools"]


# ---- Helpers --------------------------------------------------------------
def fetch_json(url, timeout=25, retries=2):
    last = None
    for attempt in range(retries + 1):
        try:
            req = Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except (URLError, HTTPError, TimeoutError, json.JSONDecodeError) as e:
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise last


def load_prev_snapshot(name):
    """Load the most recent snapshot for a source, excluding today's."""
    files = sorted(SNAP_DIR.glob(f"{name}_*.json"))
    files = [f for f in files if TODAY not in f.name]
    if not files:
        return None
    try:
        return json.loads(files[-1].read_text())
    except Exception:
        return None


def save_snapshot(name, payload):
    path = SNAP_DIR / f"{name}_{TODAY}.json"
    path.write_text(json.dumps(payload, indent=2))
    # prune: keep last 30 snapshots per source
    files = sorted(SNAP_DIR.glob(f"{name}_*.json"))
    for old in files[:-30]:
        try:
            old.unlink()
        except Exception:
            pass


# ---- Source: Apple App Store RSS -----------------------------------------
def scrape_appstore():
    """Returns list of movers with rank-velocity vs last snapshot."""
    current = {}  # key -> {rank, name, id, label}
    for country, feed, cat, label in APPSTORE_TARGETS:
        url = (f"https://itunes.apple.com/{country}/rss/{feed}/"
               f"limit={APPSTORE_LIMIT}/genre={cat}/json")
        try:
            data = fetch_json(url)
        except Exception as e:
            print(f"  [appstore] FAILED {label}: {e}", file=sys.stderr)
            continue
        entries = data.get("feed", {}).get("entry", [])
        if isinstance(entries, dict):
            entries = [entries]
        for rank, entry in enumerate(entries, start=1):
            try:
                app_id = entry["id"]["attributes"]["im:id"]
                name = entry["im:name"]["label"]
            except (KeyError, TypeError):
                continue
            key = f"{country}:{cat}:{app_id}"
            current[key] = {
                "rank": rank, "name": name, "app_id": app_id,
                "label": label, "country": country, "category": cat,
            }
        time.sleep(0.5)

    prev = load_prev_snapshot("appstore") or {}
    prev_ranks = prev.get("items", {})
    movers = []
    for key, cur in current.items():
        pr = prev_ranks.get(key)
        if pr is None:
            # New entrant to the chart — meaningful signal
            movers.append({
                "name": cur["name"], "label": cur["label"],
                "rank": cur["rank"], "prev_rank": None,
                "delta": None, "signal": "NEW to chart",
                "app_id": cur["app_id"], "country": cur["country"],
                "score": max(0, (APPSTORE_LIMIT - cur["rank"])) + 40,
            })
        else:
            delta = pr["rank"] - cur["rank"]  # positive = climbing
            if delta >= 5:  # only flag meaningful climbs
                movers.append({
                    "name": cur["name"], "label": cur["label"],
                    "rank": cur["rank"], "prev_rank": pr["rank"],
                    "delta": delta, "signal": f"+{delta} rank climb",
                    "app_id": cur["app_id"], "country": cur["country"],
                    "score": delta * 3 + max(0, APPSTORE_LIMIT - cur["rank"]),
                })

    save_snapshot("appstore", {"date": TODAY, "items": current})
    movers.sort(key=lambda m: m["score"], reverse=True)
    return movers[:25]


# ---- Source: Google Trends (optional) ------------------------------------
def scrape_trends():
    try:
        from pytrends.request import TrendReq
    except ImportError:
        print("  [trends] pytrends not installed, skipping", file=sys.stderr)
        return []
    movers = []
    try:
        py = TrendReq(hl="en-US", tz=0)
        py.build_payload(TRENDS_TERMS, timeframe="now 7-d", geo=TRENDS_GEO)
        df = py.interest_over_time()
        if df is None or df.empty:
            return []
        for term in TRENDS_TERMS:
            if term not in df.columns:
                continue
            series = df[term].tolist()
            if len(series) < 4:
                continue
            recent = sum(series[-len(series)//3:]) / max(1, len(series)//3)
            early = sum(series[:len(series)//3]) / max(1, len(series)//3)
            if early > 0 and recent / early >= 1.4:
                movers.append({
                    "term": term,
                    "signal": f"search +{int((recent/early-1)*100)}% (7d)",
                    "score": int((recent / early) * 20),
                })
    except Exception as e:
        print(f"  [trends] FAILED: {e}", file=sys.stderr)
        return []
    movers.sort(key=lambda m: m["score"], reverse=True)
    return movers


# ---- Source: Reddit post velocity ----------------------------------------
def scrape_reddit():
    current = {}
    for sub in REDDIT_SUBS:
        url = f"https://www.reddit.com/r/{sub}/hot.json?limit=25"
        try:
            data = fetch_json(url)
        except Exception as e:
            print(f"  [reddit] FAILED r/{sub}: {e}", file=sys.stderr)
            continue
        for child in data.get("data", {}).get("children", []):
            d = child.get("data", {})
            score = d.get("score", 0)
            comments = d.get("num_comments", 0)
            # crude velocity proxy: engagement per hour since posted
            age_h = max(1, (time.time() - d.get("created_utc", time.time())) / 3600)
            vel = (score + comments * 2) / age_h
            if vel >= 30:
                current[d.get("id")] = {
                    "title": d.get("title", "")[:140],
                    "sub": sub, "score": score, "comments": comments,
                    "vel": round(vel, 1),
                    "url": "https://reddit.com" + d.get("permalink", ""),
                }
        time.sleep(1.0)
    movers = sorted(current.values(), key=lambda m: m["vel"], reverse=True)
    return movers[:15]


# ---- Source: GitHub fast-rising repos ------------------------------------
def scrape_github():
    since = (UTCNOW - dt.timedelta(days=30)).strftime("%Y-%m-%d")
    movers = []
    for topic in GITHUB_TOPICS:
        url = (f"https://api.github.com/search/repositories?"
               f"q=topic:{topic}+created:>{since}&sort=stars&order=desc&per_page=5")
        try:
            data = fetch_json(url)
        except Exception as e:
            print(f"  [github] FAILED {topic}: {e}", file=sys.stderr)
            continue
        for repo in data.get("items", []):
            stars = repo.get("stargazers_count", 0)
            if stars >= 50:
                movers.append({
                    "name": repo.get("full_name"),
                    "topic": topic,
                    "stars": stars,
                    "desc": (repo.get("description") or "")[:120],
                    "url": repo.get("html_url"),
                    "signal": f"{stars}★ in <30d",
                    "score": stars,
                })
        time.sleep(1.0)
    movers.sort(key=lambda m: m["score"], reverse=True)
    return movers[:12]


# ---- Main -----------------------------------------------------------------
def main():
    print(f"Traction Radar run @ {UTCNOW.isoformat()}")
    result = {
        "generated_utc": UTCNOW.isoformat(),
        "date": TODAY,
        "appstore": [],
        "trends": [],
        "reddit": [],
        "github": [],
        "notes": [],
    }

    print("Scraping App Store...")
    try:
        result["appstore"] = scrape_appstore()
    except Exception as e:
        result["notes"].append(f"appstore error: {e}")

    print("Scraping Google Trends...")
    try:
        result["trends"] = scrape_trends()
    except Exception as e:
        result["notes"].append(f"trends error: {e}")

    print("Scraping Reddit...")
    try:
        result["reddit"] = scrape_reddit()
    except Exception as e:
        result["notes"].append(f"reddit error: {e}")

    print("Scraping GitHub...")
    try:
        result["github"] = scrape_github()
    except Exception as e:
        result["notes"].append(f"github error: {e}")

    have_history = any(SNAP_DIR.glob("appstore_*.json"))
    n_prev = len([f for f in SNAP_DIR.glob("appstore_*.json") if TODAY not in f.name])
    if n_prev == 0:
        result["notes"].append(
            "First run: velocity needs a prior snapshot to compare against. "
            "App Store rank-climb flags will start appearing on the next run. "
            "New-to-chart and other sources work immediately.")

    out = DOCS / "feed.json"
    out.write_text(json.dumps(result, indent=2))
    print(f"Wrote {out}")
    print(f"  appstore movers: {len(result['appstore'])}")
    print(f"  trends breakouts: {len(result['trends'])}")
    print(f"  reddit hot: {len(result['reddit'])}")
    print(f"  github rising: {len(result['github'])}")
    if result["notes"]:
        print("  notes:", "; ".join(result["notes"]))


if __name__ == "__main__":
    main()
