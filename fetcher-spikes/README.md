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
| nrl.com draw API | 200 OK | No | JSON | `Cache-Control: public, max-age=5`. `matchCentreUrl` = full path e.g. `/draw/nrl-premiership/2026/round-12/raiders-v-dolphins/`. Kick-off time at `clock.kickOffTimeLong` (UTC ISO 8601, e.g. `2026-05-21T09:50:00Z`) — not a top-level field. |
| nrl.com team sheet | Untested (real slug) | No | HTML (likely __NEXT_DATA__) | Team sheet URL = `https://www.nrl.com` + `matchCentreUrl`. Spike 0.1 must validate `__NEXT_DATA__` is present and map the player list JSON path. |
| nrl.com ladder | 200 OK | No | JSON | `/ladder/data?competition=111&season=YYYY`. Keys: `positions[]` (17 teams), each has `stats`, `teamNickname`, `movement`, `next`. `Cache-Control: public, max-age=5`. |
| BOM REST API | 200 OK (daily) / 400 (hourly) | No | JSON | `api.weather.bom.gov.au`. Location search by lat/lon returns geohash. Daily forecast works (8 days). Hourly endpoint returns 400 — may require different geohash precision or is region-gated. |
| BOM legacy feed | 404 | No | — | `reg.bom.gov.au/fwo/...` product URLs return 404. Do not use. |
| Open-Meteo | 200 OK | No | JSON | Free, no key. 7-day hourly + daily. Provides `precipitation_probability`, `precipitation`, `windspeed_10m`. Best fallback for BOM hourly or non-AU venues (e.g. Las Vegas). |
| Zero Tackle RSS | 200 OK | No | RSS/XML | `https://www.zerotackle.com/feed/` — 10 items, injury/team-list articles present. Article body is clean text via BeautifulSoup. |
| The Roar RSS | 200 OK | No | RSS/XML | `https://www.theroar.com.au/feed/` — 6 items, mix of sports. Filter by NRL keywords. Feed appears less frequently updated than Zero Tackle. |
| SuperCoach API | 200 (HTML body) | Likely yes | HTML redirect | All API endpoints (`/api/v3/nrl/players`, etc.) return `text/html` at ~4 KB — classic auth redirect. Needs Bearer token from browser devtools; store in Secrets Manager. |
| NRL Fantasy API | 200 (HTML body) | Likely yes | HTML redirect | `fantasy.nrl.com/api/*` returns `text/html` at ~29 KB. Same pattern as SuperCoach. Requires auth. `nrl.com/stats/data` (Champion Data proxy) returns real JSON (200, ~275 KB) with `teamStats` and `playerStats` — use this instead. |

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
