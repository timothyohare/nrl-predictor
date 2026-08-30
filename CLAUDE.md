# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 🟡 Anthropic credit balance exhausted — main site no longer at risk, action items still open (delete once resolved)

Discovered 2026-08-23. **The entire prediction pipeline has been down since
2026-08-18.** Every `nrl-predictor-agent` invocation from 2026-08-18T06:30 UTC
through 2026-08-21T23:02 UTC failed with `anthropic.BadRequestError: ... Your
credit balance is too low to access the Anthropic API`. Round 25 ended with
**0/8 matches** ever getting an OK prediction — the round was invisible on
the live site for its entire duration. Same failure hit 7 of 8 prompt
tournament variants on the 2026-08-21 run (only `stats-elo-v1`, the local
Elo/Monte Carlo variant, kept working — it doesn't call Claude).

This has happened before (2026-07-14, see `docs/lessons/2026-07-14-missing-lambda-handlers.md`)
and self-resolved once credits were topped up, but recovery surfaced latent
bugs each time, so don't assume topping up alone is sufficient — re-check
after the next scheduled orchestrator run (Tuesday) rather than closing this
out on the top-up alone.

**Also broken, found in the same investigation:** the
`nrl-predictor-missing-predictions` CloudWatch alarm never fired despite
`nrl-predictor-coverage-check` correctly detecting and logging the
under-prediction every single run ("Round 25 under-predicted: 0/8..."). The
alarm sat in state OK the whole time, reason "no datapoints were received...
treated as NonBreaching" — the metric the coverage-check emits isn't reaching
the alarm. Not yet root-caused; start from the metric emission in
`v1/orchestrator/coverage_check.py` vs. the alarm definition in
`infra/v1_stack.py`.

**Separately:** the odds API key (the-odds-api.com, unrelated service) has
been returning 401 `INVALID_KEY` since the 2026-08-18 run — a second,
independent credential lapse. The original odds-scraper crash bug
(`TypeError: Float types are not supported`, commit `4e7b80f`) is confirmed
fixed — it now fails cleanly on the auth error instead of crash-looping, but
the `odds` table is still empty because of this separate issue.

**Action needed (not code — requires the user):** top up the Anthropic
account credit balance, and rotate/renew the the-odds-api.com key.

**2026-08-23 update — main path no longer depends on this. DEPLOYED and
confirmed live.** In direct response to this incident, the main prediction
path was cut over to the local `stats-elo-v1` Elo/Monte Carlo model as
primary — the orchestrator no longer calls the Claude agent at all (see
"Phase 3 cutover" under Architecture, and
`docs/plans/10-elo-monte-carlo-predictor.md`). `cdk deploy` confirmed:
`nrl-predictor-orchestrator`'s IAM policy has no `lambda:InvokeFunction` on
`AgentLambda` and now grants `predictions`/`results` table access instead;
`AGENT_FUNCTION_NAME`/`AGENT_INVOKE_STAGGER_SECONDS` env vars are gone. A
repeat of this credit exhaustion can no longer take down main predictions —
it would still affect the 7 Claude-based tournament variants and
manual/backfill agent invocations, but not the site's primary predictions.
**Still worth confirming after the next scheduled orchestrator run** (a live
round predicted end-to-end via the new path, not just IAM/env verification)
before treating this as fully proven in production. The two action items
above (credits, odds key) still stand on their own merits — they're no
longer site-critical, but the tournament's 7 Claude variants and manual
agent backfill still depend on them.

**2026-08-26 update — Phase 3 cutover now CONFIRMED live on a real
scheduled round, not just IAM/env inspection.** Round 26's Tuesday
orchestrator run (2026-08-25T06:30 UTC) predicted 8/8 matches in ~25s, all
`prompt_version: stats-elo-v1`, all `status: OK` — the previously-open "still
worth confirming" item above is now closed. **The two action items are
still open, unresolved, and still actively biting the tournament:** round
26's tournament run wrote `simulation_predictions` rows for only
`stats-elo-v1` (8/8) — the other 7 Claude-based variants produced zero rows
again, same failure shape as round 25, so Anthropic credits have not been
topped up. The `odds` table has 0 rows for round 26 too, so the-odds-api.com
key has not been rotated either. Neither blocks the site's main predictions
(confirmed above), but both still block the tournament comparison and the
market-odds columns on the frontend. The coverage-check/alarm wiring gap
above is also still un-root-caused — not re-investigated this round since
round 26 wasn't actually under-predicted (nothing to trip the alarm on).

**2026-08-23 update — v2's EventBridge schedules disabled, not cut over.
DEPLOYED and confirmed live.** v2's whole design
(Router/Primary/Challenger/Judge/Extended, 5 LLM calls per match) only
exists to be a richer alternative to v1 — without Claude it has nothing
distinct to offer, and cutting it over the same way as v1 would just mean it
recomputes the identical stats-elo-v1 prediction v1 already writes to the
same `predictions` table. Decision (explicit user call): pause v2's
`nrl-v2-tuesday`/`-thursday`/`-friday` EventBridge rules (`enabled=False` in
`infra/v2_stack.py`, not deleted — a one-line flip re-enables them) rather
than cut it over. `cdk deploy` confirmed: `aws events list-rules` shows all
3 rules in state `DISABLED`. v2's Lambdas/code stay deployed for manual
invocation and for whenever Anthropic credit is healthy again.

---

Prompt tournament hindsight-schedule fix (`v1/tournament/orchestrator_lambda.py`
+ `infra/v1_stack.py`, docs/plans Phase 2 work) is confirmed **deployed and
live** as of 2026-08-23 — `aws events list-rules` shows all 4 tournament
schedules (Tue/Thu/Fri/Sat) plus the Sunday scorer, all ENABLED.
`simulation_predictions` has rows again (8, all `stats-elo-v1`, from the
pre-deploy 2026-08-21 run — the Claude variants failed due to the credit
issue above, not this bug). Round 25 was mid-flight when this deployed, so
judge `variant_metrics` cleanliness from round 26 onward.

## Monorepo layout (v1 + v2 coexist)

This repo hosts **both** the v1 (single-loop) and v2 (LangGraph multi-agent) predictors,
which run side by side and deploy independently.

```
common/ scrapers/ scoring/   # SHARED — single source of truth, imported bare
                             #   (`from scrapers.nrl.ladder import ...`)
v1/  agent/ api/ orchestrator/ tournament/ retrospective/   # v1.* absolute imports
v2/  agent/ api/ orchestrator/ tools/ retrospective/        # v2.* absolute imports
frontend/ scripts/ docs/     # v1 support dirs, stay at root
infra/  app.py  v1_stack.py  v2_stack.py   # ONE cdk app, two stacks
```

- **Shared code is edited once** at the root (`common/scrapers/scoring`). Never
  re-introduce a copy under `v1/` or `v2/`. Both fleets import these bare.
- **Version code uses absolute imports**: v1 code imports `v1.*`, v2 code imports `v2.*`.
- **Deploy independently**: `cd infra && cdk deploy NrlPredictorStack` (v1) /
  `cdk deploy NrlPredictorV2Stack` (v2). Both synth from the single `infra/app.py`.
- Migration history/decisions: `SPEC.md`, `tasks/plan.md`, `tasks/todo.md`.

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

## Quality gates

The repo is wired into the user-level SDLC harness (`~/.claude/bin/gate-ci.mjs`,
`gate-verify.mjs`). The binding lives in `.claude/harness.json`; the gates read
it and fall back to autodetection. `gate-ci` is also a Stop hook, so it runs at
turn-end and blocks completion on failure.

**Fast gate — `node ~/.claude/bin/gate-ci.mjs [--full] [--force]`** runs:

| Step | Command | Config |
|------|---------|--------|
| lint | `ruff check .` then `cd frontend && npm run lint` (ESLint) | `[tool.ruff]` in `pyproject.toml`; `frontend/eslint.config.mjs` |
| typecheck | `mypy .` then `cd frontend && npm run typecheck` (`tsc --noEmit`) | `[tool.mypy]` in `pyproject.toml`; `frontend/tsconfig.json` |
| test | `pytest` (with dummy AWS creds inlined) | `[tool.pytest.ini_options]` |
| build (`--full`) | `cd frontend && npm run build` | — |

Run the Python tools directly via the project venv: `.venv/bin/ruff check .`,
`.venv/bin/mypy .`. Frontend: `cd frontend && npm run lint` / `npm run typecheck`.
ESLint uses flat config (`next/core-web-vitals` + `next/typescript` via
FlatCompat) — `next lint` is deprecated and intentionally not used.

**Heavy gate — `node ~/.claude/bin/gate-verify.mjs [--keep]`** is the
boot-and-verify gate for the API read path. It stands up DynamoDB Local
(Docker), seeds a round, boots the real API Lambda over HTTP, and asserts the
predictions ⨝ results ⨝ retrospectives ⨝ odds join (incl. `is_outlier`,
most-recent-generation, and `FAILED`-row exclusion). **Requires Docker
running.** The pieces live in `scripts/gate/` (`docker-compose.yml`,
`local_setup.py`, `local_api_server.py`, `acceptance.py`) and are driven by the
`mockAws`/`setup`/`boot`/`ready`/`acceptance` keys in `.claude/harness.json`.
Scope is the API read path only — the async orchestrator/agent write path is not
booted (it doesn't fit the HTTP-readiness model).

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

## Known issues & planned improvements

### Agent occasionally emits prose instead of prediction JSON

**Scope note (2026-08-23):** the automatic per-round path no longer calls the
agent at all — see "Phase 3 cutover" below. This whole section now only
applies to **manual/backfill invocations** of `nrl-predictor-agent`.

The agent sometimes ends a run on its analysis summary (prose) rather than the
final prediction JSON object. The handler catches this and writes a `FAILED`
prediction row with `error: "Agent produced non-JSON output: ..."`. Because the
`/predictions/{round}` API only serves rows with `status == OK`, an affected
match **silently disappears** from the site — the row exists but never surfaces.
Observed on `round-15-warriors-v-sharks` (failed twice) and as trailing `FAILED`
rows in round 14. It is variance in the agent's final formatting step, not a data
problem — the match predicts fine on a re-run with the same inputs. (Note: the
"matches predict fine even with no team sheet" behaviour seen earlier was a
separate bug — team sheets were keyed by the numerical NRL matchId and never read
by the agent; fixed 2026-06-14 by keying them on the round-qualified slug, with a
one-off backfill of existing rows via `scripts/backfill_team_sheet_keys.py`.)

**Manual recovery** — re-invoke the agent for the single match; it usually
succeeds on the next attempt:

```bash
aws lambda invoke --function-name nrl-predictor-agent \
  --payload '{"matchId":"round-15-warriors-v-sharks","round":15,"season":2026}' \
  --cli-binary-format raw-in-base64-out --region ap-southeast-2 \
  --cli-read-timeout 180 /dev/null
```

**Fixed 2026-07-15 (PR #7) — JSON repair retry in the agent.** `run_agent` now
searches all final text blocks for the prediction JSON (fenced / per-block /
brace-span fallback) and, on prose output, sends one follow-up turn ("return
only the prediction JSON") before giving up and writing the `FAILED` row. The
repair turn rescued 4+ of 6 prose failures on its first production outing
(round-20 re-runs). Manual re-invocation above remains the fallback if the
repair turn also fails.

### Coverage alert when a round is under-predicted

A `FAILED`-only match (see above) leaves the round quietly short on the site.
**Implemented 2026-07-15:** `nrl-predictor-coverage-check`
(`v1/orchestrator/coverage_check.py`) runs 1h after each orchestrator window,
compares the draw's match count with the round's OK-prediction count, logs a
warning listing the missing matchIds, and emits the
`NrlPredictor/MissingPredictions` CloudWatch metric. The
`nrl-predictor-missing-predictions` alarm (threshold ≥ 1) notifies the existing
SNS alert topic (email). Invoke ad-hoc with
`{"season": 2026, "round": "current"}` to spot-check a round.

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
                                       → predict every match locally (Elo + Monte Carlo, stats-elo-v1)
                                       → predictions DynamoDB → API Lambda → Next.js front end
```

**Phase 3 cutover (2026-08-23):** the orchestrator predicts synchronously in-Lambda via
`v1/orchestrator/stats_predictor.py` (`common/stats_model/`) — no more async Claude agent
invocation on this path, no rate limit, no Anthropic credit dependency. See
`docs/plans/10-elo-monte-carlo-predictor.md` (Phase 3) for the full history: this replaced
the "fan-out: Agent Lambda per match (8s stagger)" design after the agent path went down
for round 25's entire duration (2026-08-18 to -21, Anthropic credit exhaustion — see the
incident section above). `agent_fn` (`nrl-predictor-agent`, the Claude ReAct loop) is
**not deleted** — it stays deployed for manual/backfill invocation, just no longer wired
into the automatic per-round path.

Standalone scrapers (`ladder`, `articles`, `weather`, `results`) run on their own EventBridge schedules. The orchestrator owns the per-match fan-out — the agent, draw, and team-sheet Lambdas are still callable directly for backfill/debugging, but the automatic prediction path no longer goes through the agent.

Predictions run multiple times per week: first on Tuesday after team lists drop (~4pm AEST), then updated Thursday/Friday/Saturday as new data arrives (late changes, injury news, weather). Each run generates a new prediction row; the API serves the most recent OK prediction per match. The `generation` field tracks which run produced each prediction (1 = Tuesday early, 2+ = updates).

Post-match: scoring Lambda writes scored results + triggers retrospective Lambda (async). Scoring then aggregates into `metrics`. Retrospective Lambda does a web search for match stats, stores them in `match_stats`, calls Claude Sonnet to compare prediction vs outcome, and stores the analysis in `retrospectives`. The API Lambda joins predictions ⨝ results ⨝ retrospectives ⨝ odds by `matchId` so each frontend prediction carries the actual score, post-match analysis, and market comparison (with outlier flag when prediction disagrees with the market).

### Package structure

| Package | Role |
|---------|------|
| `scrapers/nrl/` | Fetch draw, team sheets, ladder, results from nrl.com |
| `scrapers/weather/` | BOM hourly (primary) + Open-Meteo (fallback) |
| `scrapers/articles/` | RSS from Zero Tackle / The Roar; Haiku-based injury extraction |
| `scrapers/odds/` | Betting market odds from the-odds-api.com — comparison only, never agent input |
| `scrapers/shared/` | `http_client.py` (retry + delay), `s3_cache.py`, `models.py` (shared dataclasses), `constants.py` |
| `tournament/` | Prompt tournament: `variant_runner.py` (run agent with variant prompt), `variant_scorer.py` (score variants vs results), `orchestrator_lambda.py` (fan-out to workers), `worker_lambda.py` (per-variant), `scorer_lambda.py`, `seed_variants.py` (seed initial 8 variants) |
| `agent/` | LangGraph ReAct graph (`graph.py`), 14 DynamoDB-backed tools (`tools/`), system prompt (`prompt.py`), prediction schema validation (`schema.py`), budget tracker (`budget.py`). No longer on the automatic prediction path (2026-08-23 cutover) — kept for manual/backfill invocation |
| `common/stats_model/` | The local Elo + Monte Carlo predictor (`elo.py`, `simulate.py`, `ratings.py`, `confidence.py`, `predictor.py`) — no LLM, no external API. `predictor.py::predict_match()` is the single shared adapter used by both the main predictions path and the tournament's `stats-elo-v1` variant. `predict_match()`/`simulate_match()` also take optional rating-adjustment/variance-multiplier inputs (docs/plans/11-team-sheet-injury-weather-signals.md) that default to inert |
| `common/team_sheet.py` | Spine-position (jersey 1/6/7/9) comparison between two team sheets — moved here from `v1/agent/late_change.py` since both the agent's model-selection heuristic and the orchestrator's spine-disruption signal need it |
| `orchestrator/` | Per-round fan-out Lambda — scrapes draw + team sheets inline, then predicts every match synchronously via `stats_predictor.py` (Elo + Monte Carlo, no external API) |
| `retrospective/` | Post-match retrospective: Tavily search + Claude Sonnet analysis of prediction vs result |
| `scoring/` | `scorer.py` (Brier + margin error), `metrics.py` (round/season aggregation incl. confidence calibration + prompt versioning) |
| `api/` | API Gateway Lambda handlers — joins predictions ⨝ results ⨝ retrospectives ⨝ odds by matchId for the front end |
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

Current version: `v1.2` — injected retrospective lessons into system prompt; added coaching matchup, trap game detection, spine synergy, and venue profile tools; expanded chain-of-thought to 8 steps (team sheets + synergy → form + momentum → H2H + coaching → home/away → venue + weather → news → trap game → verdict).

**Since the 2026-08-23 Phase 3 cutover**, the automatic path stamps `prompt_version`/`model_used` as `"stats-elo-v1"` instead — the `pick_rate_prompt_*` metrics bucketing works unchanged (it just buckets on whatever string is in `prompt_version`), so pre- and post-cutover accuracy stay directly comparable in the `metrics` table. `v1.2` above only applies to manual/backfill agent invocations now.

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
- `odds` (when scraped): `{ market_favourite, market_margin, home_odds, away_odds, implied_home_prob, implied_away_prob }`
- `is_outlier` (boolean): true when prediction disagrees with market on winner or margin differs by >6pts

### Retrospective output schema (stored in `retrospectives` table)

`verdict` (1–2 sentences) · `hit_factors` (list) · `missed_factors` (list) · `what_actually_happened` (50–100 words) · `lesson` (one sentence) · `model_used` · `prompt_version` · `roundNumber` · `season`

### Prompt tournament

The prompt tournament (`tournament/`) runs 8 prompt variants in parallel against each match to find the most accurate prompt configuration. Variants are seeded via `python3 -m tournament.seed_variants` into the `prompt_variants` table.

- **Orchestrator** (`tournament/orchestrator_lambda.py`): fans out to worker Lambdas per variant per match
- **Worker** (`tournament/worker_lambda.py`): runs the agent with a variant prompt, writes to `simulation_predictions`
- **Scorer** (`tournament/scorer_lambda.py`): scores variant predictions against results, writes to `variant_metrics`
- Schedule: tournament orchestrator runs alongside the main orchestrator; scorer runs Sunday 20:00 AEST

Variants test dimensions: home advantage weighting, form vs H2H balance, confidence calibration, margin conservatism, and upset detection aggressiveness.

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

## Team & match identity (canonical representation)

The single source of truth is `common/` (shipped to every Lambda via the whole-repo asset),
shared in form with v2:

- **Team identity** — a team is *always* the lowercase slug (`sea-eagles`) internally. NRL
  `nickName`, full names, odds-API names and LLM output are inbound forms that **must** be
  `common.teams.to_slug()`'d at the boundary (scrapers on write, `agent/schema.py` on the agent's
  `predicted_winner`, tools on read). Display strings come from `common.teams.display()`; the API
  adds `*_name` fields and the frontend renders via `frontend/lib/teams.ts`. Registry data:
  `common/team_registry.json` (Python) + `frontend/lib/team_registry.json` (TS).
  *Invariant: no raw team name is written to a table or passed to a tool — slug at the boundary.*
- **Match identity** — `matchId` is the round-qualified slug `round-<N>-<home>-v-<away>` from
  `common.match_id`. **Every join is round-aware** (matchId or roundNumber); never a bare team-pair.

Plans: `docs/team-identity-plan-v1.md`, `docs/matchid-identity-plan-v1.md`. One-off DB migration:
`scripts/migrate_identity.py {teams,matchids}` (dry-run by default; `--apply` to write) — the
`results`/`teams`/`predictions` tables are shared with v2, so migrate once, coordinated.

## Important constraints

- **Betting market odds (`scrapers/odds/`) are for comparison only — NEVER pass odds data as input to the prediction agent.** The predictions must remain independent so the AI vs market accuracy comparison is meaningful. Odds are stored in the `odds` table and joined onto the API response post-prediction.
- All scraper requests must include a browser `User-Agent` and a random 1.5–3.0 s delay between requests.
- Table names and bucket names must be read from env vars, never hardcoded in Lambda handlers.
- Every DynamoDB write must include a `scraped_at` timestamp.
- The agent's budget check runs at the start of `lambda_handler` — if over budget, serve the cached prediction with `staleness_flag: true` rather than calling Claude.
- The rate limiter (`api/rate_limit.py`) must **fail open** if DynamoDB is unavailable — never block legitimate traffic due to infrastructure issues.
- **Anthropic account rate limit: 50,000 input tokens/minute** on Haiku 4.5. No longer relevant to the automatic prediction path since the 2026-08-23 Phase 3 cutover (`nrl-predictor-orchestrator` predicts locally now, no `AGENT_INVOKE_STAGGER_SECONDS`/agent invoke). Still applies to any batch that calls Claude directly — manual/backfill agent invocations, scoring backfills, multi-match retrospectives, the 7 Claude-based tournament variants — stagger those the same way the old orchestrator did.
- Do not add `output: 'export'` to `next.config.js` — this breaks SSR/ISR and causes Googlebot to receive an empty shell.
- **Do not delete `frontend/postcss.config.mjs`.** Without it, Tailwind directives in `globals.css` pass through unprocessed and the entire site renders as unstyled HTML (this was the production state until 2026-05-23 — easy to miss because the build succeeds).
- AWS region: `ap-southeast-2` (Sydney).
- **Do not add an `amplify.yml`** to the repo. The frontend is a Next.js SSR app in `frontend/` (monorepo). Amplify auto-detects this and runs its Next.js adapter only when there is no custom build spec. Adding `amplify.yml` bypasses the adapter, which means `deploy-manifest.json` doesn't get generated and builds fail at the deploy step. Setup details and the recreate procedure are in `docs/AMPLIFY_RECREATE.md`.
