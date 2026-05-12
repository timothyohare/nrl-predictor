"""
Spike: SuperCoach / Fantasy NRL
Tests fetching player price data as an early signal for team changes.

The insight: SuperCoach prices move on Thursday night based on projected
selections. A player whose price drops sharply is likely being rested or
is injured. This gives us a signal BEFORE the official team sheet drops.

Also tests the NRL Fantasy API as an alternative (same idea, different platform).

Sources to test:
  1. SuperCoach API (supercoach.com.au) — undocumented JSON API
  2. NRL Fantasy API (fantasy.nrl.com) — often more open
  3. Champion Data / NRL Stats API (if accessible)
"""

import json
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, */*",
    "Accept-Language": "en-AU,en;q=0.9",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

CURRENT_YEAR = 2026

def get(url, label, extra_headers=None):
    print(f"\n[GET] {label}")
    print(f"      {url}")
    t0 = time.time()
    try:
        hdrs = HEADERS.copy()
        if extra_headers:
            hdrs.update(extra_headers)
        r = SESSION.get(url, headers=hdrs, timeout=10)
        elapsed = time.time() - t0
        print(f"      Status: {r.status_code}  |  {elapsed:.2f}s  |  {len(r.content):,} bytes")
        print(f"      Content-Type: {r.headers.get('Content-Type','?')}")
        return r
    except Exception as e:
        print(f"      ERROR: {type(e).__name__}: {e}")
        return None

def section(title):
    print(f"\n{'─'*56}")
    print(f"  {title}")
    print(f"{'─'*56}")

# ── Test 1: SuperCoach API ────────────────────────────────────────────────────

def test_supercoach():
    section("1. SuperCoach (supercoach.com.au)")

    base = "https://supercoach.com.au"

    # SuperCoach historically exposes player data via undocumented API
    # These endpoints may require auth — we test without first
    endpoints = [
        ("Players list (no auth)",     f"{base}/api/v3/nrl/players?page=1&per_page=50"),
        ("Players list v4",            f"{base}/api/v4/nrl/players?page=1&limit=50"),
        ("Season players",             f"{base}/api/v3/nrl/{CURRENT_YEAR}/players"),
        ("Homepage (for auth pattern)",f"{base}/"),
    ]

    for label, url in endpoints:
        r = get(url, label)
        if r is None:
            continue
        ct = r.headers.get("Content-Type", "")
        if r.status_code == 200 and "json" in ct:
            try:
                data = r.json()
                print(f"\n  ✓ JSON response!")
                if isinstance(data, list):
                    print(f"  Array of {len(data)} items")
                    if data:
                        print(f"  First item keys: {list(data[0].keys())[:12]}")
                        p = data[0]
                        for field in ["id","first_name","last_name","team","price","locked","injury_risk"]:
                            print(f"    {field}: {p.get(field,'NOT FOUND')}")
                elif isinstance(data, dict):
                    print(f"  Dict keys: {list(data.keys())[:10]}")
            except Exception as e:
                print(f"  JSON parse error: {e}")

        elif r.status_code == 401:
            print(f"\n  → 401 Unauthorised. Auth required.")
            print(f"    Strategy: capture login token via browser devtools,")
            print(f"    store in AWS Secrets Manager, inject in Lambda scraper.")
            # Look for auth endpoints in page source
            if "html" in ct:
                soup = BeautifulSoup(r.text, "lxml")
                forms = soup.find_all("form")
                print(f"    Login forms found: {len(forms)}")
                for f in forms:
                    print(f"      action={f.get('action','?')} method={f.get('method','?')}")

        elif r.status_code == 200 and "html" in ct:
            soup = BeautifulSoup(r.text, "lxml")
            # Check for Next.js data
            nd = soup.find("script", id="__NEXT_DATA__")
            if nd:
                print(f"  Found __NEXT_DATA__ — checking for player data...")
                try:
                    page_data = json.loads(nd.text)
                    props = page_data.get("props", {}).get("pageProps", {})
                    print(f"  pageProps keys: {list(props.keys())[:8]}")
                except Exception:
                    pass

# ── Test 2: NRL Fantasy API ───────────────────────────────────────────────────

def test_nrl_fantasy():
    section("2. NRL Fantasy (fantasy.nrl.com)")

    base = "https://fantasy.nrl.com"

    endpoints = [
        ("Players JSON",         f"{base}/api/players"),
        ("Players with prices",  f"{base}/api/players?season={CURRENT_YEAR}"),
        ("Bootstrap data",       f"{base}/api/bootstrap-static/"),
        ("Homepage",             f"{base}/"),
    ]

    for label, url in endpoints:
        r = get(url, label)
        if r is None:
            continue
        ct = r.headers.get("Content-Type", "")

        if r.status_code == 200 and "json" in ct:
            try:
                data = r.json()
                print(f"\n  ✓ JSON!")
                if isinstance(data, list):
                    print(f"  {len(data)} items")
                    if data:
                        print(f"  Keys: {list(data[0].keys())[:12]}")
                        p = data[0]
                        for f in ["id","first_name","last_name","squad_id","now_cost","status"]:
                            print(f"    {f}: {p.get(f,'?')}")
                elif isinstance(data, dict):
                    print(f"  Keys: {list(data.keys())[:10]}")
                    # FPL-style bootstrap has elements.elements = players list
                    players = (data.get("players") or data.get("elements") or
                               data.get("data", {}).get("players"))
                    if players:
                        print(f"  Players found: {len(players)}")
                        print(f"  Player keys: {list(players[0].keys())[:12]}")
            except Exception as e:
                print(f"  Parse error: {e}")

        elif r.status_code in (401, 403):
            print(f"  → {r.status_code} — auth required")

# ── Test 3: Champion Data / NRL Stats ─────────────────────────────────────────

def test_nrl_stats():
    section("3. NRL Stats / Champion Data endpoints")

    # NRL uses Champion Data for statistics
    endpoints = [
        ("NRL stats API",        "https://stats.nrl.com/player/list"),
        ("NRL stats players",    f"https://stats.nrl.com/players?season={CURRENT_YEAR}"),
        ("Champion Data proxy",  f"https://www.nrl.com/stats/data?season={CURRENT_YEAR}"),
    ]

    for label, url in endpoints:
        r = get(url, label)
        if r is None:
            continue
        ct = r.headers.get("Content-Type", "")
        if r.status_code == 200 and "json" in ct:
            try:
                data = r.json()
                print(f"\n  ✓ JSON! Keys: {list(data.keys()) if isinstance(data, dict) else f'list of {len(data)}'}")
            except Exception as e:
                print(f"  JSON parse error: {e}")
        elif r.status_code == 200:
            soup = BeautifulSoup(r.text, "lxml")
            print(f"  HTML received — {len(soup.get_text()):,} chars of text")

# ── Test 4: Price movement simulation ────────────────────────────────────────

def explain_price_signal():
    section("4. Price Movement as Team Sheet Signal — Explanation")
    print("""
  The insight:
    SuperCoach/Fantasy prices update Thu night based on the platform's
    projected team selections (sourced from journalist contacts + club info).
    A player priced at $800,000 who drops to $720,000 overnight is almost
    certainly being rested or is injured.

  How to use it:
    1. Scrape player prices on Wed night (baseline)
    2. Scrape again on Thu night (post-update)
    3. Flag players with >5% price drop as "likely unavailable"
    4. This gives us a soft signal 12-24h before official team sheets

  Implementation:
    - Store Wed prices in DynamoDB: teams/{team}/fantasy/{playerId}/price_wed
    - Store Thu prices: teams/{team}/fantasy/{playerId}/price_thu
    - Lambda computes delta, flags significant drops
    - Agent tool: get_fantasy_signals(team) returns list of flagged players
    - Agent uses these as soft evidence, weighted lower than official team sheet

  Expected DynamoDB record shape:
    {
      "playerId": "12345",
      "playerName": "Nathan Cleary",
      "team": "Panthers",
      "price_wed": 950000,
      "price_thu": 870000,
      "pct_change": -8.4,
      "signal": "LIKELY_OUT",  # >5% drop
      "scraped_at": "2026-05-15T22:30:00+10:00"
    }
    """)

# ── Summary ───────────────────────────────────────────────────────────────────

def summarise():
    section("Summary / Recommendations")
    print("""
  FANTASY DATA STRATEGY:

  If SuperCoach API is open (200 JSON):
    → Fetch directly; store player prices in DynamoDB
    → Run Wed night + Thu night scrapers for delta computation

  If SuperCoach requires auth (401):
    → Option A: Register for an account; capture Bearer token via devtools;
                store in AWS Secrets Manager; inject in Lambda header
    → Option B: Use NRL Fantasy instead if it's more open
    → Option C: Skip fantasy signals entirely in MVP; add post-launch if useful

  If both require auth:
    → The price signal is a "nice to have" — the official team sheet is
      the ground truth and is always used. Fantasy prices are just an
      early warning. Don't block MVP on this.

  PRIORITY:
    MVP:   Official team sheet (nrl.com) + injury articles (RSS)
    V1.1:  Fantasy price signals
    V1.2:  Referee assignment data (nrl.com referee announcements)
    """)

# ── Entry point ───────────────────────────────────────────────────────────────

def run():
    test_supercoach()
    test_nrl_fantasy()
    test_nrl_stats()
    explain_price_signal()
    summarise()

if __name__ == "__main__":
    run()
