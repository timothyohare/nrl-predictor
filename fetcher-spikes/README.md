# NRL Predictor — Data Source Spikes

Spike scripts to probe each data source before building production scrapers.
Run these locally before writing any Lambda code.

## Setup

```bash
pip install requests beautifulsoup4 lxml
```

## Usage

```bash
# Run all spikes
python run_spikes.py

# Run a single spike
python run_spikes.py --source nrl
python run_spikes.py --source bom
python run_spikes.py --source zerotackle
python run_spikes.py --source supercoach
```

## What each spike tests

| Spike | Sources | Key questions |
|-------|---------|---------------|
| `spike_nrl.py` | nrl.com draw API, team sheet, ladder | Is there a JSON API or do we need HTML scraping? Does it need auth/cookies? |
| `spike_bom.py` | BOM REST API, BOM legacy feed, Open-Meteo | Which BOM endpoint is most reliable? Can we get hourly forecasts by lat/lon? |
| `spike_zerotackle.py` | Zero Tackle, The Roar, nrl.com news | Is RSS available? What does article text look like? Is `__NEXT_DATA__` present? |
| `spike_supercoach.py` | SuperCoach, NRL Fantasy, Champion Data | Are player prices accessible without auth? Can we use price delta as team sheet signal? |

## What to record from each spike
After running, fill in this table:

| Source | Status | Auth needed? | JSON or HTML? | Notes |
|--------|--------|-------------|--------------|-------|
| nrl.com draw API | 200 OK | No | JSON | `Cache-Control: public, max-age=5`. `matchCentreUrl` = `/draw/nrl-premiership/{year}/round-{N}/{home}-v-{away}/`. Kick-off: `clock.kickOffTimeLong` (UTC ISO 8601). Completed fixtures: `homeTeam.score` / `awayTeam.score` present when `matchState == "FullTime"`. |
| nrl.com team sheet | 200 OK | No | HTML (q-data attr) | Page is a Quasar/Vue.js app. Full team sheet embedded in `q-data` JSON attr on `<div id="vue-match-centre">`. Path: `match.homeTeam.players[]` / `match.awayTeam.players[]`. Fields: `number`, `firstName`, `lastName`, `position`, `isOnField`, `playerId`. Pre-match has 22-player squad; post-match has 18 (actual team). Also contains `match.matchId` (numeric, e.g. `"20261111110"`), `matchState`, `startTime`. |
| nrl.com results | 200 OK | No | JSON (via draw API) | No separate results endpoint. Filter draw API by `matchState == "FullTime"` — `homeTeam.score` and `awayTeam.score` are present. Confirmed: Broncos 30 – Storm 14 (2025 R27). |
| nrl.com ladder | 200 OK | No | JSON | `/ladder/data?competition=111&season=YYYY`. Keys: `positions[]` (17 teams), each has `stats`, `teamNickname`, `movement`, `next`. `Cache-Control: public, max-age=5`. |
| BOM REST API (daily) | 200 OK | No | JSON | 8-day daily forecast. Use location search (lat/lon → geohash) then `/forecasts/daily`. |
| BOM REST API (hourly) | 200 OK | No | JSON | **Requires exactly 6-char geohash** (7-char returns 400). 73-hour window. Fields: `rain.chance` (%), `rain.amount.min/max` (mm), `wind.speed_kilometre`, `wind.gust_speed_kilometre`, `wind.direction`, `temp` (°C), `time` (UTC ISO 8601). |
| BOM legacy feed | 404 | No | — | Dead. Do not use. |
| Open-Meteo | 200 OK | No | JSON | Free, no key. 7-day hourly. Use for non-AU venues (Las Vegas) or as BOM fallback. |
| Zero Tackle RSS | 200 OK | No | RSS/XML | 10 items/feed. Includes weekly team lists article and injury updates. Article body: clean text via BeautifulSoup. |
| The Roar RSS | 200 OK | No | RSS/XML | 6 items, multi-sport. Filter by NRL keyword. Less frequently updated. |
| nrl.com/stats/data | 200 OK | No | JSON | Leaderboard data only — `teamStats[].groups[].leaders[]` (team stat leaders) and `playerStats[].groups[].leaders[]` (player stat leaders). NOT per-match or head-to-head data. Useful for agent context ("Panthers lead in points scored"). |
| SuperCoach API | Auth redirect | Yes | HTML | Returns `text/html` — classic login redirect. Defer to V1.1. |
| NRL Fantasy API | Auth redirect | Yes | HTML | Same pattern. Defer to V1.1. |
| Referee data | Not available | — | — | No structured source. Not in draw API, not in match page. Skip MVP — agent can use `web_search` if needed. |

## Key patterns to look for

### JSON APIs (best case)
If a source returns clean JSON at a stable URL — use it directly.
Cache the raw response in S3 alongside the parsed DynamoDB record.

### Next.js `__NEXT_DATA__` (second best)
Many NRL sites are Next.js apps. The full page data lives in:
```html
<script id="__NEXT_DATA__" type="application/json">{ ... }</script>
```
This is far more stable than scraping CSS selectors.

### HTML scraping (last resort)
Fragile. Use only if no JSON or `__NEXT_DATA__` is available.
Abstract all selectors into a config dict so they can be updated
without changing Lambda code:
```python
SELECTORS = {
    "player_name": ".team-list__player-name",
    "player_number": ".team-list__player-number",
}
```

### Auth-gated sources
If a source returns 401/403:
1. Register for a free account
2. Capture the Bearer token via browser devtools (Network tab)
3. Store in AWS Secrets Manager: `nrl-predictor/supercoach-token`
4. Lambda fetches token at startup via `boto3.client('secretsmanager')`
5. Set a CloudWatch alarm if scraper returns 401 (token expired)

## Rate limiting strategy

Add to every scraper:
```python
import time, random
time.sleep(random.uniform(1.5, 3.0))  # between requests
```

And in Lambda, stagger invocations via EventBridge:
- nrl.com scraper: runs at :00
- BOM scraper: runs at :05  
- Article scraper: runs at :10
