# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install (editable, with dev dependencies)
pip install -e ".[dev]"

# Run all tests
pytest

# Run a single test file
pytest tests/scrapers/test_scraper_draw.py -v

# Run a single test
pytest tests/agent/test_tool_get_team_sheet.py::test_returns_correct_team_sheet -v
```

Tests use `moto` to mock AWS (DynamoDB, S3, Secrets Manager) — no real AWS credentials are needed. CI sets dummy credentials via env vars; do the same locally if boto3 complains.

## Architecture

NRL Predictor is a serverless event-driven system on AWS. The data pipeline flows:

```
EventBridge cron → Scraper Lambdas → DynamoDB + S3 → Agent Lambda (LangGraph) → predictions DynamoDB → API Lambda → Next.js front end
```

Post-match: another EventBridge cron triggers the scoring Lambda, which writes to `results`, then the metrics Lambda aggregates into `metrics`.

### Package structure

| Package | Role |
|---------|------|
| `scrapers/nrl/` | Fetch draw, team sheets, ladder, results from nrl.com |
| `scrapers/weather/` | BOM hourly (primary) + Open-Meteo (fallback) |
| `scrapers/articles/` | RSS from Zero Tackle / The Roar; Haiku-based injury extraction |
| `scrapers/shared/` | `http_client.py` (retry + delay), `s3_cache.py`, `models.py` (shared dataclasses), `constants.py` |
| `agent/` | LangGraph ReAct graph (`graph.py`), 8 DynamoDB-backed tools (`tools/`), system prompt (`prompt.py`), prediction schema validation (`schema.py`), budget tracker (`budget.py`), late-change detection (`late_change.py`) |
| `scoring/` | `scorer.py` (Brier + margin error), `metrics.py` (round/season aggregation) |
| `api/` | API Gateway Lambda handlers for front end |
| `infra/` | AWS CDK (Python) — same language as everything else |
| `fetcher-spikes/` | Throwaway scripts that probed each data source; findings recorded in `fetcher-spikes/README.md` |

### Deployed resources (ap-southeast-2, account 810429055117)

- API Gateway: `https://2jjj64x7ih.execute-api.ap-southeast-2.amazonaws.com`
- Amplify app ID: `dmazwh64vi4cy` (URL: `https://main.dmazwh64vi4cy.amplifyapp.com/`)
- Custom domain (pending DNS): `https://nrl-predictor.ohare.id.au/`

### DynamoDB tables

`predictions` (PK: `matchId`, SK: `generatedAt`) · `teams` (PK: `teamId`, SK: `round`) · `results` (PK: `matchId`, SK: `scoredAt`) · `metrics` (PK: `period`, SK: `metricName`) · `nrl-rate-limits` (PK: `pk`, TTL: `ttl`) · `claude_usage` (PK: `yearMonth`, SK: `invokedAt`) · `injuries` (PK: `pk`, SK: `sk`) · `weather` (PK: `pk`, SK: `sk`)

### Key scraping facts (from completed spikes)

- **nrl.com team sheet page** is a Quasar/Vue.js app (not Next.js — no `__NEXT_DATA__`). Full team data is embedded in the `q-data` JSON attribute on `<div id="vue-match-centre">`. Parse with BeautifulSoup → find `#vue-match-centre` → read `q-data` attr → `json.loads`. Path: `match.homeTeam.players[]` / `match.awayTeam.players[]`. Fields: `number`, `firstName`, `lastName`, `position`, `isOnField` (true = starting 13).
- **NRL results** come from the draw API (`matchState == "FullTime"`), not a separate endpoint.
- **BOM hourly** requires exactly a **6-character geohash** (location search returns 7 — truncate before calling hourly endpoint).
- **Open-Meteo** is the weather fallback for non-AU venues and BOM outages.
- SuperCoach/NRL Fantasy require auth — deferred to V1.1.
- Referee data has no structured source — agent uses `web_search` on demand.

### Agent model selection

- Standard rounds: `claude-haiku-4-5-20251001`
- Finals / high-impact late changes (halfback, hooker, or starting prop jersey numbers 7, 9, 8, 10): `claude-sonnet-4-6`
- Overridable via `AGENT_MODEL` env var.

### Prediction output schema

`predicted_winner` (string) · `predicted_margin` (int) · `confidence` (LOW/MEDIUM/HIGH) · `key_factors` (2–4 strings) · `reasoning` (200–400 words) · `data_freshness` (ISO timestamp) · `model_used` · `generated_at`

## TDD workflow

The implementation plan (`docs/IMPLEMENTATION_PLAN.md`) defines a strict TDD cycle:

1. **[SPIKE]** — throwaway script in `fetcher-spikes/` to answer unknowns
2. **[TEST]** — write a failing test. Commit it red before writing any code.
3. **[CODE]** — minimum code to make it green.
4. **[REFACTOR]** — clean up while tests stay green.

Never write `[CODE]` without a preceding `[TEST]`. Every new module has a corresponding test file under `tests/` mirroring the source structure (e.g. `scrapers/nrl/draw.py` → `tests/scrapers/test_scraper_draw.py`).

Fixture JSON files go in `tests/fixtures/` and are copied from spike output.

## Important constraints

- All scraper requests must include a browser `User-Agent` and a random 1.5–3.0 s delay between requests.
- Table names and bucket names must be read from env vars, never hardcoded in Lambda handlers.
- Every DynamoDB write must include a `scraped_at` timestamp.
- The agent's budget check runs at the start of `lambda_handler` — if over budget, serve the cached prediction with `staleness_flag: true` rather than calling Claude.
- The rate limiter (`api/rate_limit.py`) must **fail open** if DynamoDB is unavailable — never block legitimate traffic due to infrastructure issues.
- Do not add `output: 'export'` to `next.config.js` — this breaks SSR/ISR and causes Googlebot to receive an empty shell.
- AWS region: `ap-southeast-2` (Sydney).
