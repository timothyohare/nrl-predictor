"""
Spike: nrl.com
Tests three endpoints:
  1. Unofficial draw/fixtures API (JSON) — preferred over HTML scraping
  2. Team sheet HTML page for a known upcoming match
  3. Ladder JSON API

Findings to look for:
  - Is there a stable JSON API we can rely on?
  - What fields does the team sheet expose?
  - Does it require auth/cookies?
  - Response time and caching headers
"""

import json
import time
import requests
from bs4 import BeautifulSoup
from pprint import pformat

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-AU,en;q=0.9",
    "Referer": "https://www.nrl.com/",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

# ── Helpers ──────────────────────────────────────────────────────────────────

def get(url, label, as_json=False):
    print(f"\n[GET] {label}")
    print(f"      {url}")
    t0 = time.time()
    try:
        r = SESSION.get(url, timeout=10)
        elapsed = time.time() - t0
        print(f"      Status: {r.status_code}  |  {elapsed:.2f}s  |  {len(r.content):,} bytes")
        print(f"      Cache-Control: {r.headers.get('Cache-Control', 'none')}")
        print(f"      Content-Type:  {r.headers.get('Content-Type', 'unknown')}")
        if as_json:
            return r, r.json()
        return r, None
    except Exception as e:
        print(f"      ERROR: {type(e).__name__}: {e}")
        return None, None

def section(title):
    print(f"\n{'─'*56}")
    print(f"  {title}")
    print(f"{'─'*56}")

# ── Test 1: Draw / Fixtures JSON API ─────────────────────────────────────────

def test_draw_api():
    section("1. Draw / Fixtures JSON API")

    # NRL has used this pattern historically — adjust round/year as needed
    CURRENT_YEAR = 2026
    CURRENT_ROUND = 12  # round after the one just completed

    candidates = [
        (
            "Draw API v3 (by round)",
            f"https://www.nrl.com/draw/data?competition=111&season={CURRENT_YEAR}&round={CURRENT_ROUND}",
            True,
        ),
        (
            "Draw API v3 (full season)",
            f"https://www.nrl.com/draw/data?competition=111&season={CURRENT_YEAR}",
            True,
        ),
        (
            "Fixtures page (HTML fallback)",
            f"https://www.nrl.com/draw/?competition=111&season={CURRENT_YEAR}",
            False,
        ),
    ]

    match_ids = []

    for label, url, as_json in candidates:
        r, data = get(url, label, as_json=as_json)
        if r is None:
            continue

        if r.status_code == 200 and as_json and data:
            # Explore the shape of the JSON
            print(f"\n  Top-level keys: {list(data.keys()) if isinstance(data, dict) else type(data).__name__}")

            # Try to find match list
            matches = None
            for key in ["fixtures", "matches", "data", "rounds"]:
                if isinstance(data, dict) and key in data:
                    matches = data[key]
                    print(f"  Found matches under key '{key}': {len(matches)} items")
                    break

            if matches and len(matches) > 0:
                first = matches[0] if isinstance(matches, list) else matches
                print(f"\n  First match object keys: {list(first.keys()) if isinstance(first, dict) else '?'}")

                # Extract useful fields
                for field in ["matchId", "id", "homeTeam", "awayTeam", "venue", "kickOffTime", "roundTitle"]:
                    val = first.get(field, "NOT FOUND")
                    print(f"    {field}: {val}")

                # Collect match IDs for team sheet test
                id_field = next((f for f in ["matchId", "id"] if f in first), None)
                if id_field:
                    match_ids = [m[id_field] for m in matches[:3] if id_field in m]
                    print(f"\n  Sample match IDs: {match_ids}")

        elif r.status_code == 200 and not as_json:
            # Parse HTML for match links
            soup = BeautifulSoup(r.text, "lxml")
            links = soup.select("a[href*='/draw/']")
            print(f"\n  Found {len(links)} draw links in HTML")
            for a in links[:5]:
                print(f"    {a.get('href', '')}")

    return match_ids

# ── Test 2: Team Sheet ────────────────────────────────────────────────────────

def test_team_sheet(match_ids=None):
    section("2. Team Sheet")

    # Try known URL patterns — update matchId with one from test_draw_api()
    CURRENT_YEAR = 2026
    sample_id = match_ids[0] if match_ids else "20260512-0001"

    candidates = [
        (
            "Team sheet JSON API",
            f"https://www.nrl.com/draw/data/match/{sample_id}",
            True,
        ),
        (
            "Match centre JSON",
            f"https://www.nrl.com/draw/nrl-premiership/{CURRENT_YEAR}/{sample_id}",
            False,
        ),
    ]

    for label, url, as_json in candidates:
        r, data = get(url, label, as_json=as_json)
        if r is None or r.status_code != 200:
            continue

        if as_json and data:
            print(f"\n  Top-level keys: {list(data.keys()) if isinstance(data, dict) else type(data)}")

            # Look for team/player data
            for key in ["teamLists", "players", "homeTeam", "awayTeam", "lineUp"]:
                if isinstance(data, dict) and key in data:
                    sub = data[key]
                    print(f"\n  [{key}] found — type: {type(sub).__name__}")
                    if isinstance(sub, list) and sub:
                        player = sub[0]
                        print(f"  First player keys: {list(player.keys()) if isinstance(player, dict) else player}")
                    elif isinstance(sub, dict):
                        print(f"  Keys: {list(sub.keys())[:10]}")

        elif not as_json:
            soup = BeautifulSoup(r.text, "lxml")
            # Look for player name patterns
            player_els = soup.select(".player-name, .team-list__player, [class*='player']")
            print(f"\n  Player elements found: {len(player_els)}")
            for el in player_els[:8]:
                print(f"    [{el.get('class', ['?'])[0]}] {el.get_text(strip=True)[:60]}")

# ── Test 3: Ladder ────────────────────────────────────────────────────────────

def test_ladder():
    section("3. Ladder / Standings")

    CURRENT_YEAR = 2026

    candidates = [
        (
            "Ladder JSON API",
            f"https://www.nrl.com/ladder/data?competition=111&season={CURRENT_YEAR}",
            True,
        ),
        (
            "Ladder HTML page",
            f"https://www.nrl.com/ladder/?competition=111&season={CURRENT_YEAR}",
            False,
        ),
    ]

    for label, url, as_json in candidates:
        r, data = get(url, label, as_json=as_json)
        if r is None or r.status_code != 200:
            continue

        if as_json and data:
            print(f"\n  Top-level keys: {list(data.keys()) if isinstance(data, dict) else type(data)}")

            # Find ladder entries
            for key in ["ladderEntries", "positions", "data", "entries"]:
                if isinstance(data, dict) and key in data:
                    entries = data[key]
                    print(f"  Found ladder under '{key}': {len(entries)} teams")
                    if entries:
                        first = entries[0]
                        print(f"  Team entry keys: {list(first.keys()) if isinstance(first, dict) else first}")
                        # Print top 3
                        for e in entries[:3]:
                            team = e.get("teamName", e.get("team", {}).get("name", "?"))
                            pts  = e.get("points", "?")
                            pos  = e.get("position", "?")
                            print(f"    {pos}. {team} — {pts}pts")
                    break

        elif not as_json:
            soup = BeautifulSoup(r.text, "lxml")
            rows = soup.select("tr, .ladder-row, [class*='ladder']")
            print(f"\n  Ladder rows found in HTML: {len(rows)}")
            for row in rows[:5]:
                print(f"    {row.get_text(separator=' ', strip=True)[:80]}")

# ── Summary ───────────────────────────────────────────────────────────────────

def summarise():
    section("Summary / Recommendations")
    print("""
  Check results above and note:

  ✓ IDEAL: nrl.com exposes JSON APIs (status 200 + parseable data)
      → Use these directly in Lambda scrapers; much more stable than HTML
      → Cache responses in S3 with the raw JSON for debugging

  ✗ IF JSON returns 403/401:
      → May need Accept / Origin / x-requested-with headers
      → Try fetching the HTML page first to obtain session cookies,
        then hit the JSON endpoint
      → As a fallback, parse the HTML (team sheet embedded in __NEXT_DATA__)

  ✗ IF HTML is needed:
      → Check for window.__NEXT_DATA__ in the page source (Next.js apps
        embed full page props as JSON in a <script> tag — often easier
        to parse than the HTML itself)
      → Use soup.select() with class patterns found in the live DOM

  RATE LIMITING:
      → Add a 1–2s delay between requests in Lambda scrapers
      → Set a realistic User-Agent (browser string, not 'python-requests')
      → CloudWatch alarm if >20% of scrape runs return non-200

  CACHING STRATEGY:
      → Store raw response in S3: raw-scrapes/nrl/ladder/2026-RR.json
      → DynamoDB TTL: 6 hours for ladder, 1 hour for team sheets post-Friday
      → Never re-fetch if cache is <30 min old (except post-late-change trigger)
    """)

# ── Entry point ───────────────────────────────────────────────────────────────

def run():
    match_ids = test_draw_api()
    test_team_sheet(match_ids)
    test_ladder()
    summarise()

if __name__ == "__main__":
    run()
