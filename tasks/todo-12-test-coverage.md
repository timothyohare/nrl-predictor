# TODO — Plan 12 test-coverage hardening

Living checklist. See `tasks/plan-12-test-coverage.md` for detail and
`docs/plans/12-test-coverage-hardening.md` for rationale.

Baseline coverage (2026-08-30): **88%** v1 total.

## Phase 1 — API layer · `test/phase-1-api`
- [ ] `tests/api/test_api_tournament.py` (new) — 503 unconfigured, seeded leaderboard, `Decimal` serialise, season param
- [ ] `tests/api/test_api_router.py` (new) — health, 3 dispatch routes, 404, 429 rate-limit, fail-open, `path`/`rawPath`
- [ ] Extend `tests/api/test_api_predictions.py` — retro join, odds join + `is_outlier` table, optional tables unset
- [ ] Extend `tests/api/test_api_accuracy.py` — lines 11, 23
- [ ] `v1/api/` coverage ≥ 95%
- [ ] ruff + mypy + pytest (new + full) green
- [ ] committed, pushed, PR opened

## Phase 2 — Tournament scoring · `test/phase-2-tournament-scoring`
- [ ] `tests/tournament/test_scorer_lambda.py` (new) — happy path, missing env, empty round
- [ ] Extend `tests/tournament/test_variant_scorer.py` — `aggregate_variant_season()`, `get_leaderboard()`, dedup, confidence fallback
- [ ] Extend `tests/tournament/test_seed_variants.py` — 132, 151, 160–169
- [ ] `v1/tournament/` ≥ 92%, `variant_scorer.py` ≥ 95%
- [ ] ruff + mypy + pytest green
- [ ] committed, pushed, PR opened

## Phase 3 — Scoring + market · `test/phase-3-scoring`
- [ ] Extend `tests/scoring/test_metrics.py` — `aggregate_market_season()` (writes, dedup, no-odds, all-unplayed)
- [ ] Extend `tests/scoring/test_scorer_lambda.py` — retro trigger, season agg, no-prediction early return
- [ ] `scoring/` ≥ 92%
- [ ] ruff + mypy + pytest green
- [ ] committed, pushed, PR opened

## Phase 4 — Scrapers · `test/phase-4-scrapers`
- [ ] Extend `tests/scrapers/test_scraper_weather.py` — Open-Meteo fallback, geohash truncation, both-fail
- [ ] Extend `tests/scrapers/test_odds_lambda_handler.py` — 401 INVALID_KEY clean-fail, empty response
- [ ] Extend `tests/scrapers/test_scraper_articles.py` — `rss.py` 17–18, 37, 41–42
- [ ] Extend `tests/scrapers/test_backfill.py` — `backfill.py` 41–43, 72–78
- [ ] every `scrapers/**` file ≥ 90%
- [ ] ruff + mypy + pytest green
- [ ] committed, pushed, PR opened

## Phase 5 — Agent graph · `test/phase-5-agent-graph`
- [ ] Extend `tests/agent/test_agent_graph.py` — `_extract_prediction_json` (4 shapes), JSON-repair retry (2 outcomes), budget-exceeded cached serve, `_execute_tool` dispatch, `_with_cache_breakpoint`
- [ ] `v1/agent/graph.py` ≥ 90%
- [ ] ruff + mypy + pytest green
- [ ] committed, pushed, PR opened

## Phase 6 — Write-path boot-and-verify · `test/phase-6-write-path`
- [ ] `scripts/gate/write_path_setup.py` (new)
- [ ] `scripts/gate/bdd/write_path.feature` + `test_write_path.py` (new) — orchestrator predict, generation bump, coverage-check metric, scoring + retro
- [ ] `.claude/harness.json` `acceptance` extended (read + write features)
- [ ] `node ~/.claude/bin/gate-verify.mjs` green
- [ ] committed, pushed, PR opened

## Phase 7 — Frontend infra · `test/phase-7-frontend`
- [ ] Vitest + Testing Library tooling, `vitest.config.ts`, setup file, `package.json` scripts, ESLint allowance
- [ ] `frontend/lib/teams.test.ts` (mirror `tests/common/test_teams.py`)
- [ ] `frontend/lib/teamColors.test.ts`
- [ ] `frontend/lib/api.test.ts`
- [ ] `frontend/components/MatchCard.test.tsx`
- [ ] `frontend/components/RoundSelector.test.tsx`, `AccuracyCharts.test.tsx`
- [ ] `frontend/lib` ≥ 90%, components ≥ 70%
- [ ] lint + typecheck + `npm test` green
- [ ] committed, pushed, PR opened

## Phase 8 — Enforce · `test/phase-8-enforce` (after 1–7 merge)
- [ ] `pytest-cov` dev dep; `[tool.coverage.run]` + `--cov-fail-under` in `pyproject.toml`
- [ ] `.claude/harness.json` `test` keeps cov flags + runs frontend suite
- [ ] frontend `test:cov` V8 thresholds
- [ ] `node ~/.claude/bin/gate-ci.mjs --force --full` green; break a line → gate reds
- [ ] `--cov-fail-under` ratcheted to achieved number
- [ ] committed, pushed, PR opened

## Rollup
- [ ] All phase PRs merged
- [ ] Final coverage number recorded here
- [ ] `docs/plans/12-*.md` status → done
