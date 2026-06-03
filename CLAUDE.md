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

## Post-round operations

After a round completes, run these steps in order:

### 1. Scrape results

Writes the final scores into the `results` DynamoDB table:

```bash
aws lambda invoke \
  --function-name nrl-predictor-results-scraper \
  --payload '{"season": 2026, "round": 11}' \
  --cli-binary-format raw-in-base64-out \
  --region ap-southeast-2 \
  /dev/null
```

Change `round` to the completed round number.

### 2. Score predictions and trigger retrospectives

Reads matchIds from the `predictions` table, invokes the scoring Lambda for each match (which then async-triggers the retrospective Lambda):

```bash
# Preview without invoking anything
AWS_DEFAULT_REGION=ap-southeast-2 python3 scripts/score_round.py --round 11 --season 2026 --dry-run

# Run for real
AWS_DEFAULT_REGION=ap-southeast-2 python3 scripts/score_round.py --round 11 --season 2026
```

Retrospective analyses appear in the predictions API response (under `retrospective`) ~30–60 seconds after scoring completes.

---

## CDK deploy

The CDK app lives in `infra/` and is written in Python. `aws-cdk-lib` is **not** in the main project venv — it must be installed separately:

```bash
# One-time setup (system-level, needed because infra/ has no venv of its own)
pip3 install aws-cdk-lib constructs --break-system-packages

# Deploy from the infra/ directory
cd infra
AWS_DEFAULT_REGION=ap-southeast-2 cdk deploy --require-approval never
```

The CDK Docker bundling step (for the deps Lambda layer) requires Docker to be running. The deploy takes ~2 minutes. Stack outputs are printed at the end — API endpoint and Agent Lambda ARN are stable and match what's in `CLAUDE.md`.

To preview changes without deploying:

```bash
cd infra
AWS_DEFAULT_REGION=ap-southeast-2 cdk diff
```

## Architecture

NRL Predictor is a serverless event-driven system on AWS. The data pipeline flows:

```
EventBridge cron → Orchestrator Lambda → (draw + team-sheet scrape inline)
                                       → fan-out: Agent Lambda per match (8s stagger)
                                       → predictions DynamoDB → API Lambda → Next.js front end
```

Standalone scrapers (`ladder`, `articles`, `weather`, `results`) run on their own EventBridge schedules. The orchestrator owns the per-match fan-out — agent, draw, and team-sheet Lambdas are still callable directly for backfill/debugging, but the production path is always through the orchestrator.

Predictions run multiple times per week: first on Tuesday after team lists drop (~4pm AEST), then updated Thursday/Friday/Saturday as new data arrives (late changes, injury news, weather). Each run generates a new prediction row; the API serves the most recent OK prediction per match. The `generation` field tracks which run produced each prediction (1 = Tuesday early, 2+ = updates).

Post-match: scoring Lambda writes scored results + triggers retrospective Lambda (async). Scoring then aggregates into `metrics`. Retrospective Lambda does a web search for match stats, stores them in `match_stats`, calls Claude Sonnet to compare prediction vs outcome, and stores the analysis in `retrospectives`. The API Lambda joins predictions ⨝ results ⨝ retrospectives by `matchId` so each frontend prediction carries the actual score and any post-match analysis.

### Package structure

| Package | Role |
|---------|------|
| `scrapers/nrl/` | Fetch draw, team sheets, ladder, results from nrl.com |
| `scrapers/weather/` | BOM hourly (primary) + Open-Meteo (fallback) |
| `scrapers/articles/` | RSS from Zero Tackle / The Roar; Haiku-based injury extraction |
| `scrapers/odds/` | Betting market odds from the-odds-api.com — comparison only, never agent input |
| `scrapers/shared/` | `http_client.py` (retry + delay), `s3_cache.py`, `models.py` (shared dataclasses), `constants.py` |
| `tournament/` | Prompt tournament: `variant_runner.py` (run agent with variant prompt), `variant_scorer.py` (score variants vs results), `orchestrator_lambda.py` (fan-out to workers), `worker_lambda.py` (per-variant), `scorer_lambda.py`, `seed_variants.py` (seed initial 8 variants) |
| `agent/` | LangGraph ReAct graph (`graph.py`), 8 DynamoDB-backed tools (`tools/`), system prompt (`prompt.py`), prediction schema validation (`schema.py`), budget tracker (`budget.py`), late-change detection (`late_change.py`) |
| `orchestrator/` | Per-round fan-out Lambda — scrapes draw + team sheets inline, then async-invokes the agent per match (staggered to respect Anthropic rate limit) |
| `retrospective/` | Post-match retrospective: Tavily search + Claude Sonnet analysis of prediction vs result |
| `scoring/` | `scorer.py` (Brier + margin error), `metrics.py` (round/season aggregation incl. confidence calibration + prompt versioning) |
| `api/` | API Gateway Lambda handlers — joins predictions ⨝ results ⨝ retrospectives by matchId for the front end |
| `frontend/` | Next.js 15 SSR app on Amplify. Tailwind + custom Tailwind palette (`nrl-blue`/`gold`/`cream`/`paper`/`red`), Bungee (display) + Nunito (body) via `next/font/google`, team-color accents per match card from `frontend/lib/teamColors.ts`. **Requires `postcss.config.mjs`** for Tailwind to be processed — Next won't pick up Tailwind from `tailwind.config.ts` alone. |
| `infra/` | AWS CDK (Python) — same language as everything else |
| `fetcher-spikes/` | Throwaway scripts that probed each data source; findings recorded in `fetcher-spikes/README.md` |

### Deployed resources (ap-southeast-2, account 810429055117)

- API Gateway: `https://2jjj64x7ih.execute-api.ap-southeast-2.amazonaws.com`
- Amplify app ID: `d60x8viwfcqtj` (URL: `https://main.d60x8viwfcqtj.amplifyapp.com/`)
- Custom domain: `https://nrl-predictor.ohare.id.au/`

### DynamoDB tables

`predictions` (PK: `matchId`, SK: `generatedAt`) · `teams` (PK: `teamId`, SK: `round`) · `results` (PK: `matchId`, SK: `scoredAt`) · `metrics` (PK: `period`, SK: `metricName`) · `nrl-rate-limits` (PK: `pk`, TTL: `ttl`) · `claude_usage` (PK: `yearMonth`, SK: `invokedAt`) · `injuries` (PK: `pk`, SK: `sk`) · `weather` (PK: `pk`, SK: `sk`) · `retrospectives` (PK: `matchId`, SK: `generatedAt`) · `match_stats` (PK: `matchId`, SK: `scraped_at`) · `odds` (PK: `matchId`, SK: `scrapedAt`) · `prompt_variants` (PK: `variantId`, SK: `version`) · `simulation_predictions` (PK: `pk` = `matchId#variantId`, SK: `generatedAt`) · `variant_metrics` (PK: `variantId`, SK: `period`)

### Prompt versioning

The agent prompt version is tracked in `agent/prompt.py` as `PROMPT_VERSION`. Every prediction is stamped with this value. The scoring Lambda carries it through to the scored result. Metrics aggregation writes `pick_rate_prompt_v1_1` (etc.) to the `metrics` table so accuracy can be compared across prompt versions.

To bump the version: update `PROMPT_VERSION` and add an entry to `PROMPT_CHANGELOG` in `agent/prompt.py`.

Current version: `v1.1` — added explicit chain-of-thought assessment order (team sheets → form → H2H → home/away → weather → news → verdict).

### Key scraping facts (from completed spikes)

- **nrl.com team sheet page** is a Quasar/Vue.js app (not Next.js — no `__NEXT_DATA__`). Full team data is embedded in the `q-data` JSON attribute on `<div id="vue-match-centre">`. Parse with BeautifulSoup → find `#vue-match-centre` → read `q-data` attr → `json.loads`. Path: `match.homeTeam.players[]` / `match.awayTeam.players[]`. Fields: `number`, `firstName`, `lastName`, `position`, `isOnField` (true = starting 13).
- **NRL results** come from the draw API (`matchState == "FullTime"`), not a separate endpoint.
- **BOM hourly** requires exactly a **6-character geohash** (location search returns 7 — truncate before calling hourly endpoint).
- **Open-Meteo** is the weather fallback for non-AU venues and BOM outages.
- SuperCoach/NRL Fantasy require auth — deferred to V1.1.
- Referee data has no structured source — agent uses `web_search` on demand.
- **Post-match stats** are currently fetched via Tavily web search in the retrospective Lambda and stored as text snippets in `match_stats`. A spike to parse the NRL match centre `q-data` post-match for structured data (try scorers, possession, tackles) is deferred to a future iteration.

### Agent model selection

- Standard rounds: `claude-haiku-4-5-20251001`
- Finals / high-impact late changes (spine positions — fullback 1, five-eighth 6, halfback 7, hooker 9): `claude-sonnet-4-6`
- Retrospective analysis: `claude-sonnet-4-6`
- Overridable via `AGENT_MODEL` env var.

### matchId format

Round-qualified: `round-{N}-{home-slug}-v-{away-slug}` (e.g. `round-12-panthers-v-broncos`). Produced by `scrapers/nrl/draw.py` from the NRL `matchCentreUrl`. Pre-2026-05 predictions used unqualified IDs (`panthers-v-broncos`); both formats coexist in the `predictions` table — the frontend's `splitMatchId` strips the `round-N-` prefix when present.

### Prediction output schema

`predicted_winner` (string) · `predicted_margin` (int) · `confidence` (LOW/MEDIUM/HIGH) · `key_factors` (2–4 strings) · `reasoning` (200–400 words) · `data_freshness` (ISO timestamp) · `model_used` · `generated_at` · `prompt_version` · `generation` (int — 1 = first prediction, 2+ = update from later run)

The `/predictions/{round}` API additionally joins each prediction with:
- `result` (when match is scored): `{ winner, homeTeam, awayTeam, homeScore, awayScore, margin }`
- `retrospective` (when generated): see schema below

### Retrospective output schema (stored in `retrospectives` table)

`verdict` (1–2 sentences) · `hit_factors` (list) · `missed_factors` (list) · `what_actually_happened` (50–100 words) · `lesson` (one sentence) · `model_used` · `prompt_version` · `roundNumber` · `season`

### Metrics calibration

`metrics` table stores confidence calibration, prompt version pick rates, and market accuracy for the season period:
- `pick_rate_high_confidence`, `pick_rate_medium_confidence`, `pick_rate_low_confidence`
- `pick_rate_prompt_v1_1` (one per prompt version, dots replaced with underscores)
- `market_pick_rate`, `market_mean_margin_error`, `market_brier_score` — betting market accuracy (written by `scoring/metrics.py::aggregate_market_season`)

## TDD workflow

The implementation plan (`docs/IMPLEMENTATION_PLAN.md`) defines a strict TDD cycle:

1. **[SPIKE]** — throwaway script in `fetcher-spikes/` to answer unknowns
2. **[TEST]** — write a failing test. Commit it red before writing any code.
3. **[CODE]** — minimum code to make it green.
4. **[REFACTOR]** — clean up while tests stay green.

Never write `[CODE]` without a preceding `[TEST]`. Every new module has a corresponding test file under `tests/` mirroring the source structure (e.g. `scrapers/nrl/draw.py` → `tests/scrapers/test_scraper_draw.py`).

Fixture JSON files go in `tests/fixtures/` and are copied from spike output.

## Important constraints

- **Betting market odds (`scrapers/odds/`) are for comparison only — NEVER pass odds data as input to the prediction agent.** The predictions must remain independent so the AI vs market accuracy comparison is meaningful. Odds are stored in the `odds` table and joined onto the API response post-prediction.
- All scraper requests must include a browser `User-Agent` and a random 1.5–3.0 s delay between requests.
- Table names and bucket names must be read from env vars, never hardcoded in Lambda handlers.
- Every DynamoDB write must include a `scraped_at` timestamp.
- The agent's budget check runs at the start of `lambda_handler` — if over budget, serve the cached prediction with `staleness_flag: true` rather than calling Claude.
- The rate limiter (`api/rate_limit.py`) must **fail open** if DynamoDB is unavailable — never block legitimate traffic due to infrastructure issues.
- **Anthropic account rate limit: 50,000 input tokens/minute** on Haiku 4.5. The orchestrator staggers agent invokes by 8s (configurable via `AGENT_INVOKE_STAGGER_SECONDS` env on `nrl-predictor-orchestrator`) to stay under this. Any new batch that calls Claude (scoring backfills, multi-match retrospectives, etc.) needs the same treatment.
- Do not add `output: 'export'` to `next.config.js` — this breaks SSR/ISR and causes Googlebot to receive an empty shell.
- **Do not delete `frontend/postcss.config.mjs`.** Without it, Tailwind directives in `globals.css` pass through unprocessed and the entire site renders as unstyled HTML (this was the production state until 2026-05-23 — easy to miss because the build succeeds).
- AWS region: `ap-southeast-2` (Sydney).
- **Do not add an `amplify.yml`** to the repo. The frontend is a Next.js SSR app in `frontend/` (monorepo). Amplify auto-detects this and runs its Next.js adapter only when there is no custom build spec. Adding `amplify.yml` bypasses the adapter, which means `deploy-manifest.json` doesn't get generated and builds fail at the deploy step. Setup details and the recreate procedure are in `docs/AMPLIFY_RECREATE.md`.
