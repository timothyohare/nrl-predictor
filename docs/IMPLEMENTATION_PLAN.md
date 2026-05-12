# NRL Predictor — Detailed Implementation Plan

*Companion to [NRL_Predictor_Working_Backwards.md](NRL_Predictor_Working_Backwards.md) — Section 4*
*Last updated: 2026-05-12*

## Confirmed Decisions

| Decision | Choice | Notes |
|----------|--------|-------|
| IaC tool | **AWS CDK (Python)** | Same language as scrapers and agent; better for complex IAM/EventBridge/DynamoDB wiring |
| AWS region | **ap-southeast-2 (Sydney)** | Lowest latency to BOM + nrl.com; data stays in AU |
| `matchCentreUrl` format | `/draw/nrl-premiership/{year}/round-{N}/{home}-v-{away}/` | Full path confirmed from live API. Team sheet URL = `https://www.nrl.com` + this path |
| Kick-off time field | `clock.kickOffTimeLong` (UTC ISO 8601) | e.g. `2026-05-21T09:50:00Z`. Not a top-level field — nested inside `clock` object |
| Historical backfill | **2025 + 2026 seasons** | Run once after results scraper is built; use same `parse_results` function over all rounds |
| Web search provider | **Tavily** | Purpose-built for AI agents; 1,000 searches/month free tier; store key in Secrets Manager |

---

## How to use this plan

Each task is a single checkbox. Work top to bottom. TDD cycle is explicit:

1. **[SPIKE]** — run a throwaway script to answer an open question before writing production code
2. **[TEST]** — write a failing test first. Do not move to [CODE] until the test is committed and red.
3. **[CODE]** — write the minimum code to make the test green. No gold-plating.
4. **[REFACTOR]** — clean up while all tests stay green. Then move on.
5. **[INFRA]** — AWS/config task with no code test (but document what you verified manually).
6. **[DEPLOY]** — ship it.

> **TDD rule:** Every [CODE] task must have a corresponding [TEST] task immediately before it.
> If you find yourself writing code without a red test — stop, write the test first.

---

## Phase 0 — Remaining Spikes

*These open questions must be answered before writing any Lambda code.*
*Spike scripts go in `fetcher-spikes/`. Update `fetcher-spikes/README.md` after each.*

### 0.1 Team Sheet via `__NEXT_DATA__`

`matchCentreUrl` format confirmed: `/draw/nrl-premiership/{year}/round-{N}/{home}-v-{away}/`
Kick-off time confirmed: `clock.kickOffTimeLong` (UTC ISO 8601). Team sheet page not yet validated.

- [ ] **[SPIKE]** Fetch `https://www.nrl.com` + `matchCentreUrl` for a real round-12 match (e.g. `/draw/nrl-premiership/2026/round-12/raiders-v-dolphins/`).
  - Does it return 200?
  - Is `<script id="__NEXT_DATA__">` present in the HTML?
  - Parse the `__NEXT_DATA__` JSON. Find where the 1–17 player list lives (look for `homeTeam.players` or similar).
  - Document the JSON path to: player name, jersey number, position, bench/starting status.
  - Check if the page requires cookies from a prior session request.
- [ ] **[SPIKE]** Test the same for a match that has already been played (should have actual lineup vs named squad).
- [ ] Update `fetcher-spikes/README.md` and `fetcher-spikes/results.html` with findings.

### 0.2 NRL Results / Final Scores API

Post-match scoring (Phase 4) requires fetching the final score after each match.
This source has not been spiked at all.

- [ ] **[SPIKE]** Test `https://www.nrl.com/draw/data?competition=111&season=2026&round=11` — do completed fixture objects contain a final score? Look for fields like `homeTeam.score`, `awayTeam.score`, `matchState: "FullTime"`.
- [ ] **[SPIKE]** Test `https://www.nrl.com/draw/nrl-premiership/2026/{completed-slug}` — does `__NEXT_DATA__` contain the final score for completed matches?
- [ ] **[SPIKE]** Check if there is a dedicated results endpoint: `https://www.nrl.com/results/data?competition=111&season=2026&round=11`.
- [ ] Document the chosen approach and the JSON path to home/away final scores.
- [ ] Update README + results.html.

### 0.3 BOM Hourly Investigation

BOM hourly returned 400 for both test venues. Daily (8-day) works fine.
Open-Meteo is the current fallback but BOM hourly is preferable for AU venues.

- [ ] **[SPIKE]** Try BOM hourly with shortened geohash (5 chars instead of 7): `api.weather.bom.gov.au/v1/locations/{5-char-geohash}/forecasts/hourly`.
- [ ] **[SPIKE]** Try the BOM 3-hourly endpoint if one exists: `...forecasts/3-hourly`.
- [ ] **[SPIKE]** Check the BOM API docs at `api.weather.bom.gov.au` for any version or endpoint changes.
- [ ] If BOM hourly cannot be fixed: document Open-Meteo as the definitive hourly source and close this spike.
- [ ] Update README + results.html.

### 0.4 Head-to-Head / Historical Stats

`nrl.com/stats/data` returns `teamStats` and `playerStats` (~275 KB JSON), but the
internal structure was not explored. The agent tool `get_head_to_head()` depends on this.

- [ ] **[SPIKE]** Parse the full JSON from `nrl.com/stats/data?season=2026`. Document top-level keys and shape of `teamStats[]` and `playerStats[]`.
- [ ] **[SPIKE]** Determine if head-to-head (team A vs team B, last N years) is available in this response or requires a separate endpoint.
- [ ] **[SPIKE]** Test `https://www.nrl.com/stats/data?season=2025` — is multi-season data available for building head-to-head tables?
- [ ] **[SPIKE]** Check `https://www.nrl.com/stats/` HTML page for `__NEXT_DATA__` — may contain richer structured data.
- [ ] Document what head-to-head data is available and what must be derived by aggregating historical round-by-round results.
- [ ] Update README + results.html.

### 0.5 Referee Assignment Data

The working backwards doc lists referee tendencies as an input factor. No spike yet.

- [ ] **[SPIKE]** Check `https://www.nrl.com/draw/data?competition=111&season=2026&round=12` — do fixture objects contain a referee field?
- [ ] **[SPIKE]** Check the match `__NEXT_DATA__` page for referee information.
- [ ] **[SPIKE]** Check `https://www.nrl.com/news/?tagKey=referees` — is there a structured referee assignment article each week?
- [ ] If no structured source exists: document that referee data is out of scope for MVP and can be added via web_search tool if needed.
- [ ] Update README + results.html.

---

## Phase 1 — AWS Infrastructure

*No business logic — just provision the environment. Verify manually. No TDD needed here.*

### 1.1 Repository and Project Structure

- [ ] **[INFRA]** Create `nrl-predictor/` monorepo with directories:
  ```
  nrl-predictor/
  ├── scrapers/          # Lambda scraper functions
  │   ├── nrl/
  │   ├── weather/
  │   └── articles/
  ├── agent/             # LangGraph agent + tools
  ├── scoring/           # Post-match scoring + metrics Lambda
  ├── frontend/          # Next.js app
  ├── infra/             # CDK or SAM templates
  ├── tests/             # All tests (mirrors src structure)
  │   ├── scrapers/
  │   ├── agent/
  │   └── scoring/
  ├── fetcher-spikes/    # Already exists
  └── docs/              # Already exists
  ```
- [ ] **[INFRA]** Add `pyproject.toml` (or `requirements.txt` per Lambda) with: `pytest`, `pytest-mock`, `requests`, `boto3`, `moto[dynamodb,s3]`, `beautifulsoup4`, `lxml`, `langgraph`, `anthropic`.
- [ ] **[INFRA]** Add `pytest.ini` with `testpaths = tests` and `addopts = -v`.
- [ ] **[INFRA]** Add GitHub Actions workflow: run `pytest` on every push to `main` and every PR.

### 1.2 DynamoDB Tables

- [ ] **[INFRA]** Create DynamoDB table `predictions` — PK: `matchId` (S), SK: `generatedAt` (S).
- [ ] **[INFRA]** Create DynamoDB table `teams` — PK: `teamId` (S), SK: `round` (S).
- [ ] **[INFRA]** Create DynamoDB table `results` — PK: `matchId` (S), SK: `scoredAt` (S).
- [ ] **[INFRA]** Create DynamoDB table `metrics` — PK: `period` (S), SK: `metricName` (S).
- [ ] **[INFRA]** Create DynamoDB table `rate_limits` — PK: `ipAddress` (S), SK: `window` (S); TTL attribute: `expiresAt`.
- [ ] **[INFRA]** Create DynamoDB table `claude_usage` — PK: `yearMonth` (S), SK: `invokedAt` (S).
- [ ] **[INFRA]** Verify all tables appear in AWS console with correct key schema.

### 1.3 S3 Bucket

- [ ] **[INFRA]** Create S3 bucket `nrl-predictor-raw-scrapes` with versioning enabled, no public access, default encryption.
- [ ] **[INFRA]** Add S3 lifecycle rule: delete objects older than 90 days under prefix `raw-scrapes/`.
- [ ] **[INFRA]** Verify bucket policy blocks public access.

### 1.4 IAM Roles

- [ ] **[INFRA]** Create IAM role `nrl-predictor-scraper-role` with permissions: `dynamodb:PutItem`, `dynamodb:GetItem` on scraper-relevant tables; `s3:PutObject` on `nrl-predictor-raw-scrapes`; `logs:CreateLogGroup`, `logs:PutLogEvents`.
- [ ] **[INFRA]** Create IAM role `nrl-predictor-agent-role` with permissions: all scraper permissions + `dynamodb:Query`, `dynamodb:Scan` on all tables; `s3:GetObject`; `secretsmanager:GetSecretValue`.
- [ ] **[INFRA]** Create IAM role `nrl-predictor-scoring-role` with: `dynamodb:PutItem`, `dynamodb:GetItem`, `dynamodb:Query` on `predictions`, `results`, `metrics`.

### 1.5 Secrets Manager

- [ ] **[INFRA]** Create secret `nrl-predictor/anthropic-api-key` — store the Anthropic API key.
- [ ] **[INFRA]** Create secret `nrl-predictor/tavily-api-key` — store the Tavily API key (provided out-of-band).
- [ ] **[INFRA]** Create placeholder secret `nrl-predictor/supercoach-token` — value `PENDING` (will populate in V1.1).
- [ ] **[INFRA]** Verify agent Lambda role can read all three secrets.

---

## Phase 2 — Data Collection (Scrapers)

*Each scraper follows the same TDD cycle:*
*Test → Code → Refactor → Integration test against live URL (manual, not in CI).*

### 2.1 Shared scraper utilities

- [ ] **[TEST]** `tests/scrapers/test_http_client.py` — assert `get_with_retry(url)` returns `(status_code, body)` tuple; assert it retries on 5xx (mock 500 then 200); assert it raises `ScraperError` after 3 failures; assert random delay between 1.5–3.0s is applied (mock `time.sleep`, check call args are in range).
- [ ] **[CODE]** `scrapers/shared/http_client.py` — implement `get_with_retry(url, headers, max_retries=3, session=None)`. Hardcode NRL browser User-Agent. Random delay between requests.
- [ ] **[REFACTOR]** Extract delay range and max_retries as module-level constants.
- [ ] **[TEST]** `tests/scrapers/test_s3_cache.py` — assert `save_raw(bucket, key, body)` calls `s3.put_object` with correct args; assert `load_raw(bucket, key)` returns body string; assert `load_raw` returns `None` for missing key (mock `NoSuchKey`).
- [ ] **[CODE]** `scrapers/shared/s3_cache.py` — implement `save_raw` and `load_raw` using `boto3`.
- [ ] **[REFACTOR]** Add content-type header (`application/json` vs `text/html`) to `save_raw`.

### 2.2 NRL Draw Scraper

- [ ] **[TEST]** `tests/scrapers/test_scraper_draw.py`:
  - Load a fixture JSON file (`tests/fixtures/nrl_draw_round12.json` — copy from spike output) and assert `parse_draw(data)` returns a list of `Match` objects with fields: `match_id` (slug from `matchCentreUrl`), `home_team`, `away_team`, `venue`, `round_number`, `kick_off` (None if not present), `match_state`.
  - Assert `parse_draw` handles an empty `fixtures` list without error.
  - Assert `parse_draw` skips fixture objects missing `matchCentreUrl`.
- [ ] **[CODE]** `scrapers/nrl/draw.py` — implement `fetch_draw(season, round_number)` calling the draw API; implement `parse_draw(data)` returning `list[Match]`. `Match` is a dataclass.
- [ ] **[REFACTOR]** Move `Match` dataclass to `scrapers/shared/models.py`.
- [ ] **[TEST]** Add test: `lambda_handler(event, context)` writes each match to DynamoDB `teams` table and raw JSON to S3 (use `moto` to mock both); assert correct number of `put_item` calls.
- [ ] **[CODE]** Add `lambda_handler` to `scrapers/nrl/draw.py`.
- [ ] **[REFACTOR]** Table name and bucket name read from env vars, not hardcoded.

### 2.3 NRL Team Sheet Scraper

*Depends on completing Spike 0.1 first — do not start until `__NEXT_DATA__` JSON path is confirmed.*

- [ ] **[TEST]** `tests/scrapers/test_scraper_team_sheet.py`:
  - Create fixture file `tests/fixtures/nrl_team_sheet_next_data.json` — copy the relevant portion of `__NEXT_DATA__` from the spike.
  - Assert `parse_team_sheet(next_data, team)` returns a `TeamSheet` dataclass with: `team_id`, `round`, `match_id`, `players: list[Player]` (each Player has `name`, `jersey_number`, `position`, `status: "starting"|"bench"|"reserve"`).
  - Assert `parse_team_sheet` raises `TeamSheetNotFound` if the expected JSON path is absent.
  - Assert `parse_team_sheet` raises `TeamSheetNotFound` if players list is empty.
- [ ] **[CODE]** `scrapers/nrl/team_sheet.py` — implement `fetch_team_sheet_page(match_slug)` (HTTP GET + extract `__NEXT_DATA__`); implement `parse_team_sheet(next_data, team)`.
- [ ] **[REFACTOR]** `Player` and `TeamSheet` dataclasses into `scrapers/shared/models.py`.
- [ ] **[TEST]** Assert `lambda_handler` writes parsed `TeamSheet` to DynamoDB `teams` table and raw HTML to S3; assert it handles `TeamSheetNotFound` gracefully (logs warning, does not raise).
- [ ] **[CODE]** Add `lambda_handler`.
- [ ] **[REFACTOR]** Add `scraped_at` timestamp field to all DynamoDB writes.

### 2.4 NRL Ladder Scraper

- [ ] **[TEST]** `tests/scrapers/test_scraper_ladder.py`:
  - Create fixture `tests/fixtures/nrl_ladder.json`.
  - Assert `parse_ladder(data)` returns `list[LadderPosition]` with fields: `position`, `team_name`, `played`, `wins`, `losses`, `draws`, `points`, `for_against_diff`, `percentage`.
  - Assert `parse_ladder` returns 17 items for a full season response.
- [ ] **[CODE]** `scrapers/nrl/ladder.py` — implement `fetch_ladder(season)` and `parse_ladder(data)`.
- [ ] **[REFACTOR]** Merge `LadderPosition` into `scrapers/shared/models.py`.
- [ ] **[TEST]** Assert `lambda_handler` writes ladder to DynamoDB and S3.
- [ ] **[CODE]** Add `lambda_handler`.

### 2.5 NRL Results Scraper

*Depends on completing Spike 0.2 first — do not start until results JSON path is confirmed.*

- [ ] **[TEST]** `tests/scrapers/test_scraper_results.py`:
  - Create fixture `tests/fixtures/nrl_draw_round11_completed.json` — a draw API response for a completed round.
  - Assert `parse_results(data)` returns `list[MatchResult]` with fields: `match_id`, `home_team`, `away_team`, `home_score`, `away_score`, `winner`, `margin`, `match_state`.
  - Assert `parse_results` only returns fixtures where `match_state == "FullTime"`.
  - Assert `parse_results` returns an empty list if no completed matches.
- [ ] **[CODE]** `scrapers/nrl/results.py` — implement `fetch_results(season, round_number)` and `parse_results(data)`.
- [ ] **[REFACTOR]** `MatchResult` into `scrapers/shared/models.py`.
- [ ] **[TEST]** Assert `lambda_handler` writes `MatchResult` records to DynamoDB `results` table.
- [ ] **[CODE]** Add `lambda_handler`.

### 2.6 Historical Results Backfill

*Run once after 2.5 is deployed. Populates `results` table with 2025 + 2026 data so
`get_recent_form` and `get_head_to_head` are useful from day one.*

- [ ] **[TEST]** `tests/scrapers/test_backfill.py`:
  - Assert `backfill_season(season=2025, max_round=27)` calls `fetch_results` for each round and writes only `MatchResult` records where `match_state == "FullTime"` (skips byes and future rounds).
  - Assert it is idempotent — running twice does not create duplicate records (use DynamoDB `put_item` with no overwrite condition, or a conditional write).
  - Assert it skips rounds that return an empty fixtures list without raising.
- [ ] **[CODE]** `scrapers/nrl/backfill.py` — implement `backfill_season(season, max_round=27)`. Reuses `fetch_results` and `parse_results` from `scrapers/nrl/results.py`. Adds a 2-second delay between rounds to avoid rate limiting. Logs a summary: rounds processed, records written, records skipped.
- [ ] **[CODE]** `scrapers/nrl/backfill.py` — add `__main__` block so it can be run locally: `python3 -m scrapers.nrl.backfill --seasons 2025 2026`.
- [ ] **[DEPLOY]** Run backfill locally (not as a Lambda — no need to deploy it): `python3 -m scrapers.nrl.backfill --seasons 2025 2026`. Verify record count in DynamoDB console (~27 rounds × 8 matches × 2 seasons ≈ 430 records).

### 2.8 Weather Scraper

- [ ] **[TEST]** `tests/scrapers/test_scraper_weather.py`:
  - Create fixture `tests/fixtures/open_meteo_response.json` — copy from spike output.
  - Assert `parse_open_meteo(data, target_date, target_hour)` returns `WeatherForecast` with: `venue`, `date`, `hour`, `rain_chance_pct`, `rain_mm`, `wind_kmh`, `temp_c`.
  - Assert it selects the correct hour slot from the hourly array.
  - Assert it raises `WeatherDataUnavailable` if `target_date` is beyond the 7-day window.
  - Create fixture `tests/fixtures/bom_daily_response.json` — copy from spike output.
  - Assert `parse_bom_daily(data, target_date)` returns `WeatherForecast` (daily granularity — no hour field).
  - Assert BOM geohash lookup: `get_geohash(lat, lon)` returns the geohash string from a mocked BOM location response.
- [ ] **[CODE]** `scrapers/weather/weather.py` — implement `fetch_open_meteo(lat, lon, forecast_days=7)`, `parse_open_meteo`, `fetch_bom_daily(lat, lon)`, `parse_bom_daily`, `get_geohash(lat, lon)`.
- [ ] **[CODE]** `scrapers/weather/venues.py` — hardcoded dict mapping venue name → `(lat, lon)` for all NRL venues (including GIO Stadium, Suncorp, Accor, AAMI Park, BlueBet, McDonald Jones, PointsBet, etc).
- [ ] **[REFACTOR]** `WeatherForecast` into `scrapers/shared/models.py`. Open-Meteo is primary; BOM daily is fallback. Encapsulate fallback logic in `get_forecast(venue, date, kickoff_hour)`.
- [ ] **[TEST]** Assert `lambda_handler` calls `get_forecast` for each venue in the current round, writes results to DynamoDB and S3.
- [ ] **[CODE]** Add `lambda_handler`.

### 2.9 Article Scraper (RSS + Haiku extraction)

- [ ] **[TEST]** `tests/scrapers/test_scraper_articles.py`:
  - Create fixture `tests/fixtures/zerotackle_rss.xml` — copy sample RSS from spike.
  - Assert `parse_rss(xml_text, source_name)` returns `list[Article]` with: `title`, `url`, `published_at`, `source`.
  - Assert `parse_rss` filters out articles older than 48 hours.
  - Assert `parse_rss` returns only items matching an NRL team keyword list.
  - Create fixture `tests/fixtures/article_body.html` — copy sample article HTML from spike.
  - Assert `extract_body_text(html)` returns a clean string with no HTML tags, nav or footer text.
  - Assert `extract_body_text` returns text of at least 100 characters for a valid article.
- [ ] **[CODE]** `scrapers/articles/rss.py` — implement `fetch_rss(url)` and `parse_rss(xml_text, source_name)`. `Article` dataclass into `models.py`.
- [ ] **[CODE]** `scrapers/articles/body.py` — implement `fetch_article_body(url)` and `extract_body_text(html)` using BeautifulSoup.
- [ ] **[TEST]** `tests/scrapers/test_haiku_extractor.py`:
  - Assert `extract_injury_mentions(article_text, claude_client)` calls the Claude API with the correct prompt and returns `list[InjuryMention]` with: `player`, `team`, `status`, `detail`.
  - Use a mock Claude client that returns a hardcoded JSON response.
  - Assert the function handles a malformed JSON response from Claude by returning an empty list (not raising).
- [ ] **[CODE]** `scrapers/articles/haiku_extractor.py` — implement `extract_injury_mentions(article_text, claude_client)` using `claude-haiku-4-5-20251001`. Prompt: *"Extract all player injury/availability mentions. Return JSON array: [{player, team, status, detail}]."*
- [ ] **[REFACTOR]** Move Claude model ID strings to a shared `scrapers/shared/constants.py`.
- [ ] **[TEST]** Assert `lambda_handler` fetches RSS from Zero Tackle + The Roar; deduplicates by URL; for each new article fetches body, runs Haiku extraction, saves raw text + extracted JSON to S3, writes metadata to DynamoDB.
- [ ] **[CODE]** Add `lambda_handler`.

### 2.10 EventBridge Schedules

- [ ] **[INFRA]** Create EventBridge rule `nrl-scraper-wednesday` — cron: `0 8 ? * WED *` (18:00 AEST = 08:00 UTC). Targets: draw scraper Lambda.
- [ ] **[INFRA]** Create EventBridge rule `nrl-scraper-thursday` — cron: `0 12 ? * THU *` (22:00 AEST). Targets: draw + team sheet + ladder + article scraper Lambdas (staggered by 5 min each).
- [ ] **[INFRA]** Create EventBridge rule `nrl-scraper-friday-pm` — cron: `0 4 ? * FRI *` (14:00 AEST). Targets: team sheet + article scraper.
- [ ] **[INFRA]** Create EventBridge rule `nrl-scraper-friday-night` — cron: `0 12 ? * FRI *` (22:00 AEST). Targets: team sheet + weather + article scraper.
- [ ] **[INFRA]** Create EventBridge rule `nrl-scraper-saturday-am` — cron: `0 23 ? * FRI *` (09:00 AEST Sat). Targets: team sheet + weather + article scraper.

### 2.11 CloudWatch Alarms

- [ ] **[INFRA]** Create CloudWatch alarm on each scraper Lambda: alarm if invocation `Errors > 0` within 30 minutes of scheduled run. Action: SNS email to developer.
- [ ] **[INFRA]** Create CloudWatch alarm on draw scraper: alarm if `Items written to DynamoDB == 0` (custom metric) — indicates empty fixture response.

---

## Phase 3 — Agent and Tools

*All tools are pure functions backed by DynamoDB/S3 queries. Test with moto mocks. Agent graph tested with a pre-loaded DynamoDB state.*

### 3.1 Agent Tool: `get_team_sheet`

- [ ] **[TEST]** `tests/agent/test_tool_get_team_sheet.py`:
  - Use `moto` to seed DynamoDB `teams` table with a fixture `TeamSheet` record.
  - Assert `get_team_sheet(team="Panthers", round=12)` returns the correct `TeamSheet`.
  - Assert it raises `ToolError` if no record found.
  - Assert it raises `ToolError` if `scraped_at` is older than 24 hours (stale data guard).
- [ ] **[CODE]** `agent/tools/team_sheet.py` — implement `get_team_sheet(team, round)` querying DynamoDB.
- [ ] **[REFACTOR]** Stale-data threshold configurable via env var `MAX_DATA_AGE_HOURS`.

### 3.2 Agent Tool: `get_injury_list`

- [ ] **[TEST]** `tests/agent/test_tool_get_injury_list.py`:
  - Seed DynamoDB with injury mention records (written by article scraper Haiku step).
  - Assert `get_injury_list(team="Panthers")` returns `list[InjuryMention]` for that team only.
  - Assert it returns an empty list (not an error) if no records exist.
  - Assert it only returns records with `scraped_at` within the last 48 hours.
- [ ] **[CODE]** `agent/tools/injury_list.py` — implement `get_injury_list(team)` querying DynamoDB.

### 3.3 Agent Tool: `get_recent_form`

- [ ] **[TEST]** `tests/agent/test_tool_get_recent_form.py`:
  - Seed DynamoDB `results` table with 6 rounds of results.
  - Assert `get_recent_form(team="Panthers", n=5)` returns the 5 most recent `MatchResult` objects for that team, sorted by date descending.
  - Assert it returns fewer than `n` items if fewer are available (no error).
- [ ] **[CODE]** `agent/tools/recent_form.py` — implement `get_recent_form(team, n=5)`.

### 3.4 Agent Tool: `get_head_to_head`

*Depends on Spike 0.4 — implement after head-to-head data structure is confirmed.*

- [ ] **[TEST]** `tests/agent/test_tool_get_head_to_head.py`:
  - Seed `results` table with 3 years of Sharks vs Eels results at both venues.
  - Assert `get_head_to_head(team_a="Sharks", team_b="Eels", venue="PointsBet Stadium")` returns a `HeadToHead` summary: `team_a_wins`, `team_b_wins`, `draws`, `avg_margin`, `last_3_results`.
  - Assert it filters by venue correctly.
  - Assert it returns a neutral summary (zeros) if no history exists.
- [ ] **[CODE]** `agent/tools/head_to_head.py` — implement `get_head_to_head(team_a, team_b, venue)` by querying DynamoDB `results` and aggregating.

### 3.5 Agent Tool: `get_weather`

- [ ] **[TEST]** `tests/agent/test_tool_get_weather.py`:
  - Seed DynamoDB with a `WeatherForecast` for `Suncorp Stadium` on `2026-05-16`.
  - Assert `get_weather(venue="Suncorp Stadium", date="2026-05-16")` returns the `WeatherForecast`.
  - Assert it raises `ToolError` if no forecast is available for that venue+date.
- [ ] **[CODE]** `agent/tools/weather.py` — implement `get_weather(venue, date)`.

### 3.6 Agent Tool: `get_ladder`

- [ ] **[TEST]** `tests/agent/test_tool_get_ladder.py`:
  - Seed DynamoDB with a 17-team ladder.
  - Assert `get_ladder()` returns `list[LadderPosition]` sorted by position.
  - Assert it returns the most recently scraped ladder (by `scraped_at`).
- [ ] **[CODE]** `agent/tools/ladder.py` — implement `get_ladder()`.

### 3.7 Agent Tool: `search_articles`

- [ ] **[TEST]** `tests/agent/test_tool_search_articles.py`:
  - Seed S3 with 3 extracted JSON files under `articles/extracted/`.
  - Seed DynamoDB article metadata table with titles, dates, teams.
  - Assert `search_articles(query="Panthers halfback injury")` returns chunks from articles mentioning Panthers and injury within the last 48 hours.
  - Assert it returns an empty list if no relevant articles exist.
  - Assert it never returns articles older than 48 hours.
- [ ] **[CODE]** `agent/tools/search_articles.py` — implement `search_articles(query)`. Simple keyword match against team names + injury terms in the extracted `InjuryMention` records. Return the `detail` field as context strings.

### 3.8 Agent Tool: `web_search`

- [ ] **[TEST]** `tests/agent/test_tool_web_search.py`:
  - Mock the web search API client.
  - Assert `web_search(query="NRL Panthers late change round 12")` returns `list[str]` (text snippets).
  - Assert it raises `ToolError` with a helpful message if the search API is unavailable.
- [ ] **[CODE]** `agent/tools/web_search.py` — implement `web_search(query)` using the `tavily-python` SDK. Fetch key from Secrets Manager: `nrl-predictor/tavily-api-key`. Return `list[str]` of result snippets (content field from each result).
- [ ] **[INFRA]** Add `nrl-predictor/tavily-api-key` to Secrets Manager (API key provided out-of-band). Add `tavily-python` to agent dependencies.

### 3.9 Prediction Output Schema

- [ ] **[TEST]** `tests/agent/test_prediction_schema.py`:
  - Assert `validate_prediction(raw_dict)` returns a validated `Prediction` dataclass for a well-formed dict.
  - Assert it raises `ValidationError` if `predicted_winner` is not a known NRL team name.
  - Assert it raises `ValidationError` if `confidence` is not one of `LOW`, `MEDIUM`, `HIGH`.
  - Assert it raises `ValidationError` if `key_factors` has fewer than 2 or more than 4 items.
  - Assert `validate_player_names(prediction, team_sheet_home, team_sheet_away)` returns `True` if all players named in `reasoning` appear in one of the two team sheets (basic substring check).
- [ ] **[CODE]** `agent/schema.py` — implement `Prediction` dataclass, `validate_prediction`, `validate_player_names`. Known team names list is a constant.

### 3.10 System Prompt

- [ ] **[TEST]** `tests/agent/test_system_prompt.py`:
  - Assert `build_system_prompt()` returns a non-empty string.
  - Assert it contains the word "cite" (grounding instruction).
  - Assert it contains the JSON schema field names.
  - Assert it contains the instruction to flag uncertainty.
- [ ] **[CODE]** `agent/prompt.py` — implement `build_system_prompt()`. Persona: experienced NRL analyst. Instructions: reason step by step, cite data source for each claim, flag when data is missing, output valid JSON conforming to schema.

### 3.11 LangGraph Agent Graph

- [ ] **[TEST]** `tests/agent/test_agent_graph.py`:
  - Seed DynamoDB + S3 (moto) with a complete data set for one match (Panthers vs Broncos, Round 12).
  - Assert `run_agent(match_id="panthers-v-broncos-20260515")` returns a `Prediction` object that passes `validate_prediction`.
  - Assert the agent calls at least `get_team_sheet` and `get_weather` tools (verify via mock call tracking).
  - Assert the agent does not hallucinate team names not in the known teams list (validated by `validate_prediction`).
  - Use a mocked Claude client returning a hardcoded valid prediction JSON to make this test fast and free.
- [ ] **[CODE]** `agent/graph.py` — implement LangGraph ReAct graph with nodes for: tool dispatch, Claude inference, output parsing, player validation. Wire all 8 tools.
- [ ] **[REFACTOR]** Model selection logic: Haiku for standard rounds, Sonnet for finals/high-impact late changes. Configurable via `AGENT_MODEL` env var override.
- [ ] **[TEST]** `tests/agent/test_model_selection.py` — assert `select_model(match_context)` returns `claude-haiku-4-5-20251001` for a regular season match and `claude-sonnet-4-6` for a finals match.
- [ ] **[CODE]** `agent/model_selection.py` — implement `select_model(match_context)`.

### 3.12 Budget Tracker

- [ ] **[TEST]** `tests/agent/test_budget.py`:
  - Assert `record_usage(input_tokens, output_tokens, model, table)` writes a record to DynamoDB `claude_usage` with correct token counts and estimated cost.
  - Assert `get_month_to_date_spend(table)` returns the sum of costs for the current calendar month.
  - Assert `check_budget(threshold_usd, table)` raises `BudgetExceeded` when month-to-date spend exceeds threshold.
- [ ] **[CODE]** `agent/budget.py` — implement all three functions. Cost table: Haiku input $0.80/MTok, output $4/MTok; Sonnet input $3/MTok, output $15/MTok (update if pricing changes).
- [ ] **[REFACTOR]** Call `record_usage` after every Claude API call in the graph. Call `check_budget` at the start of `lambda_handler` — serve cached prediction with staleness flag if over budget.

---

## Phase 4 — Automation and Post-Match Scoring

### 4.1 Agent Lambda

- [ ] **[TEST]** `tests/agent/test_agent_lambda.py`:
  - Assert `lambda_handler(event, context)` with `event = {"matchId": "panthers-v-broncos-20260515"}` calls `run_agent` and writes the resulting `Prediction` to DynamoDB `predictions` table.
  - Assert `lambda_handler` catches `BudgetExceeded` and writes a cached prediction record with `staleness_flag: true` instead.
  - Assert `lambda_handler` catches unhandled exceptions and writes a `status: "FAILED"` record to DynamoDB (so the front end can show "prediction unavailable").
- [ ] **[CODE]** `agent/lambda_handler.py` — implement `lambda_handler`.
- [ ] **[DEPLOY]** Deploy agent Lambda with 1 GB memory, 5-minute timeout, agent IAM role.
- [ ] **[INFRA]** EventBridge rule `nrl-agent-friday-night` — after team sheets drop, one invocation per match in the round. Pass `matchId` in the event payload. Stagger invocations by 30 seconds to avoid hitting Claude throughput limits simultaneously.

### 4.2 Post-Match Scoring Lambda

- [ ] **[TEST]** `tests/scoring/test_scorer.py`:
  - Seed `predictions` table with a prediction for `matchId = "panthers-v-broncos-20260515"`.
  - Seed `results` table with actual score Panthers 24 – Broncos 18.
  - Assert `score_prediction(match_id, results_table, predictions_table)` returns a `ScoredResult` with: `correct_pick=True`, `predicted_margin_error=6`, `within_6_pts=True`, `within_12_pts=True`, `brier_component` (float, based on confidence).
  - Assert `correct_pick=False` when the wrong team is predicted.
  - Assert Brier score component: `HIGH` confidence mapped to `p=0.85`, `MEDIUM` to `p=0.65`, `LOW` to `p=0.55`. Formula: `(p - outcome)^2`.
- [ ] **[CODE]** `scoring/scorer.py` — implement `score_prediction`.
- [ ] **[TEST]** `tests/scoring/test_scorer_lambda.py` — assert `lambda_handler(event)` calls `score_prediction`, writes `ScoredResult` to `results` table, then invokes the metrics aggregation Lambda.
- [ ] **[CODE]** `scoring/lambda_handler.py`.
- [ ] **[DEPLOY]** Deploy scoring Lambda. EventBridge rule: trigger 90 minutes after each scheduled kick-off.

### 4.3 Metrics Aggregation Lambda

- [ ] **[TEST]** `tests/scoring/test_metrics.py`:
  - Seed `results` table with 10 scored results for Round 12 (7 correct, 3 wrong).
  - Assert `aggregate_round(round=12, season=2026)` returns a `RoundMetrics` with: `correct_picks=7`, `total=10`, `pick_rate=0.70`, `mean_margin_error` (float), `brier_score` (float).
  - Assert it also computes season-to-date metrics across all seeded rounds.
  - Assert it writes metrics records to the `metrics` table.
- [ ] **[CODE]** `scoring/metrics.py` — implement `aggregate_round` and `aggregate_season`.
- [ ] **[CODE]** `scoring/metrics_lambda.py` — `lambda_handler` invokes both aggregation functions after each match is scored.
- [ ] **[DEPLOY]** Deploy metrics Lambda. Invoke from scoring Lambda (not directly from EventBridge).

### 4.4 Late-Change Re-Run

- [ ] **[TEST]** `tests/agent/test_late_change.py`:
  - Assert `is_high_impact_change(old_team_sheet, new_team_sheet)` returns `True` when halfback, hooker or a starting prop has changed.
  - Assert it returns `False` for interchange/reserve swaps.
- [ ] **[CODE]** `agent/late_change.py` — implement `is_high_impact_change`. Use jersey number positions 7, 9, 8, 10 as high-impact signals.
- [ ] **[INFRA]** Team sheet scraper Lambda: after writing a new team sheet, compare with previous version in DynamoDB; if changed, emit an EventBridge event `TeamSheetChanged` with `match_id` and `is_high_impact` flag.
- [ ] **[INFRA]** EventBridge rule on `TeamSheetChanged`: invoke agent Lambda for that match. If `is_high_impact=true`, use Sonnet; otherwise Haiku.

---

## Phase 5 — Front End

### 5.1 Next.js Scaffold

- [ ] **[INFRA]** `npx create-next-app@latest frontend --typescript --tailwind --app` in `nrl-predictor/frontend/`.
- [ ] **[INFRA]** Add `next.config.js` — do not add `output: 'export'`. Set `revalidate` per page in route segments, not globally.
- [ ] **[INFRA]** Connect GitHub repo to AWS Amplify. Configure build command: `cd frontend && npm run build`.
- [ ] **[INFRA]** Amplify env vars: `NEXT_PUBLIC_API_BASE_URL`, `API_GATEWAY_URL` (server-side only).

### 5.2 API Lambda (serves front end)

- [ ] **[TEST]** `tests/api/test_api_predictions.py`:
  - Assert `GET /predictions/{round}` returns a JSON array of predictions for that round from DynamoDB.
  - Assert it returns 404 if no predictions exist for that round.
  - Assert it returns a `staleness` field per prediction (age of `generated_at`).
- [ ] **[CODE]** `api/predictions.py` — Lambda-backed API Gateway route.
- [ ] **[TEST]** `tests/api/test_api_accuracy.py`:
  - Assert `GET /accuracy` returns season-to-date metrics from DynamoDB `metrics` table.
  - Assert it always returns fresh data (no CloudFront caching on this route).
- [ ] **[CODE]** `api/accuracy.py`.
- [ ] **[INFRA]** API Gateway HTTP API with routes: `GET /predictions/{round}`, `GET /accuracy`, `GET /health`. Configure 5-minute CloudFront cache on `/predictions/*`, no cache on `/accuracy`.

### 5.3 Predictions Page

- [ ] **[CODE]** `frontend/app/predictions/[round]/page.tsx` — ISR page (`revalidate: 300`). Fetch prediction list from API. Render match cards.
- [ ] **[CODE]** Match card component: shows home vs away team names, predicted winner (bold), predicted margin, confidence badge (colour-coded LOW/MEDIUM/HIGH), 2–4 key factors as bullet points, "Show reasoning" expandable section with full `reasoning` text, `generated_at` timestamp, late-change badge if re-generated.
- [ ] **[CODE]** Round selector: dropdown or tabs for rounds 1–27 (finals included). Defaults to the current round.
- [ ] **[CODE]** "Prediction unavailable" state for `status: "FAILED"` records and `staleness_flag: true` records.
- [ ] Verify: `curl https://nrl-predictor.ohare.id.au/predictions/12` returns full prediction HTML (not a loading shell). This is a manual check — not in CI.

### 5.4 Accuracy Dashboard Page

- [ ] **[CODE]** `frontend/app/accuracy/page.tsx` — SSR (no revalidate; always fresh). Fetch from `/accuracy` API.
- [ ] **[CODE]** Season scorecard: large stat blocks — correct picks %, mean margin error, Brier score.
- [ ] **[CODE]** Round-by-round bar chart (use `recharts` or `chart.js`) — one bar per round showing pick rate.
- [ ] **[CODE]** Confidence calibration chart — scatter: x = predicted confidence tier, y = actual accuracy for that tier.
- [ ] **[CODE]** Team accuracy table — rows per team, columns: predicted correctly N times, incorrect N times, accuracy %.
- [ ] **[CODE]** Current round table — all matches with prediction + result side by side once match completes.

### 5.5 Static Pages

- [ ] **[CODE]** `frontend/app/page.tsx` — landing page. Short description of the platform, link to current round predictions, accuracy headline stat.
- [ ] **[CODE]** `frontend/app/how-it-works/page.tsx` — SSG. Explain data sources, agent reasoning, TDD approach, honesty principle.
- [ ] **[CODE]** `frontend/public/robots.txt` — allow Googlebot/Bingbot on all pages, block on `/api/`; block GPTBot, CCBot, Google-Extended, anthropic-ai; `Crawl-delay: 10`.

---

## Phase 6 — Hardening and Launch

### 6.1 Abuse Prevention

- [ ] **[INFRA]** Deploy CloudFront distribution in front of Amplify + API Gateway.
- [ ] **[CODE]** CloudFront Function `block-scrapers` (viewer-request): allow known search crawler UAs (googlebot, bingbot, slurp, duckduckbot); block python-requests, curl, wget, scrapy, go-http-client, AI crawlers, UA < 10 chars. Return 403 at edge.
- [ ] **[TEST]** Unit test the CloudFront Function locally using the CloudFront Function testing tool: assert Googlebot passes, assert `python-requests/2.28` returns 403.
- [ ] **[INFRA]** API Gateway stage throttle: 10 rps sustained, 20 burst.
- [ ] **[TEST]** `tests/api/test_rate_limit.py` — assert `check_rate_limit(ip, table)` returns `True` (allow) under 20 req/hr, returns `False` (block) on the 21st request within the hour. Assert TTL on the DynamoDB counter is set to 1 hour from first request.
- [ ] **[CODE]** `api/rate_limit.py` — implement `check_rate_limit(ip, dynamodb_client)`.

### 6.2 DNS and TLS

- [ ] **[INFRA]** In Amplify console: add custom domain `nrl-predictor.ohare.id.au`. Amplify provisions ACM certificate automatically.
- [ ] **[INFRA]** In Route 53: add CNAME `nrl-predictor` → Amplify's CloudFront domain. No new hosted zone required (subdomain of existing `ohare.id.au`).
- [ ] **[INFRA]** Verify ACM certificate is ISSUED and HTTPS works: `curl -I https://nrl-predictor.ohare.id.au`.

### 6.3 Spend Controls

- [ ] **[INFRA]** Anthropic Console: set monthly hard cap to $20 USD. Set 50% alert email at $10 USD.
- [ ] **[INFRA]** CloudWatch alarm: fire on `BudgetExceeded` custom metric (emitted by `agent/budget.py`). Action: SNS email.
- [ ] **[INFRA]** CloudWatch alarm: fire if any Lambda's `Duration` exceeds 4 minutes (approaching 5-minute timeout). Action: SNS email.

### 6.4 Load and Integration Testing

- [ ] **[TEST]** Run agent end-to-end (no mocks) against live DynamoDB/S3 for one historical round with known outcomes. Manually evaluate prediction quality.
- [ ] **[TEST]** Simulate Saturday morning peak: invoke 8 agent Lambdas in parallel (one per match). Verify no throttling or timeout errors.
- [ ] **[TEST]** Verify scraper retry logic: manually block a scraper URL (via firewall rule or env var) and confirm it retries 3 times, then exits cleanly with a CloudWatch alarm firing.

### 6.5 Pre-Launch Checklist

- [ ] Verify `robots.txt` is accessible at `https://nrl-predictor.ohare.id.au/robots.txt`.
- [ ] Verify Google Search Console shows site being indexed (submit sitemap).
- [ ] Verify accuracy dashboard is visible and populated with at least one round of historical data.
- [ ] Verify prediction `generated_at` timestamp is always displayed on the front end.
- [ ] Verify "prediction unavailable" state renders correctly (not a blank card).
- [ ] Confirm monthly AWS cost estimate by reviewing Cost Explorer after first full week of operation.
- [ ] Soft launch: share with 3–5 people and collect feedback before public announcement.

---

## Additional Spikes Summary

| # | Spike | Blocking what? | Status |
|---|-------|---------------|--------|
| 0.1 | Team sheet `__NEXT_DATA__` with real slug | Team sheet scraper (2.3) | Not started |
| 0.2 | NRL results / final scores API | Results scraper (2.5), Post-match scoring (4.2) | Not started |
| 0.3 | BOM hourly investigation | Weather scraper (2.6) | Not started |
| 0.4 | Head-to-head stats structure | `get_head_to_head` tool (3.4) | Not started |
| 0.5 | Referee assignment data | Agent prompt quality | Not started |

---

## Quick Reference: Test File Map

| Module | Test file |
|--------|-----------|
| `scrapers/shared/http_client.py` | `tests/scrapers/test_http_client.py` |
| `scrapers/shared/s3_cache.py` | `tests/scrapers/test_s3_cache.py` |
| `scrapers/nrl/draw.py` | `tests/scrapers/test_scraper_draw.py` |
| `scrapers/nrl/team_sheet.py` | `tests/scrapers/test_scraper_team_sheet.py` |
| `scrapers/nrl/ladder.py` | `tests/scrapers/test_scraper_ladder.py` |
| `scrapers/nrl/results.py` | `tests/scrapers/test_scraper_results.py` |
| `scrapers/weather/weather.py` | `tests/scrapers/test_scraper_weather.py` |
| `scrapers/articles/rss.py` | `tests/scrapers/test_scraper_articles.py` |
| `scrapers/articles/haiku_extractor.py` | `tests/scrapers/test_haiku_extractor.py` |
| `agent/tools/team_sheet.py` | `tests/agent/test_tool_get_team_sheet.py` |
| `agent/tools/injury_list.py` | `tests/agent/test_tool_get_injury_list.py` |
| `agent/tools/recent_form.py` | `tests/agent/test_tool_get_recent_form.py` |
| `agent/tools/head_to_head.py` | `tests/agent/test_tool_get_head_to_head.py` |
| `agent/tools/weather.py` | `tests/agent/test_tool_get_weather.py` |
| `agent/tools/ladder.py` | `tests/agent/test_tool_get_ladder.py` |
| `agent/tools/search_articles.py` | `tests/agent/test_tool_search_articles.py` |
| `agent/tools/web_search.py` | `tests/agent/test_tool_web_search.py` |
| `agent/schema.py` | `tests/agent/test_prediction_schema.py` |
| `agent/prompt.py` | `tests/agent/test_system_prompt.py` |
| `agent/graph.py` | `tests/agent/test_agent_graph.py` |
| `agent/model_selection.py` | `tests/agent/test_model_selection.py` |
| `agent/budget.py` | `tests/agent/test_budget.py` |
| `agent/late_change.py` | `tests/agent/test_late_change.py` |
| `agent/lambda_handler.py` | `tests/agent/test_agent_lambda.py` |
| `scoring/scorer.py` | `tests/scoring/test_scorer.py` |
| `scoring/lambda_handler.py` | `tests/scoring/test_scorer_lambda.py` |
| `scoring/metrics.py` | `tests/scoring/test_metrics.py` |
| `api/predictions.py` | `tests/api/test_api_predictions.py` |
| `api/accuracy.py` | `tests/api/test_api_accuracy.py` |
| `api/rate_limit.py` | `tests/api/test_rate_limit.py` |

---

*— End of Implementation Plan —*
