# Plan 12 — Test-coverage hardening

**Status:** proposed
**Author:** 2026-08-30
**Motivation:** A coverage audit (`coverage run -m pytest tests`) put v1 line
coverage at **88%** overall, but that average hides several near-zero pockets on
code paths that have *already caused production incidents* (agent JSON-repair,
odds auth lapse, tournament scorer). The frontend has **no test infrastructure
at all**. Coverage is also not enforced — the 88% is a one-off local number, not
a gate.

This plan closes the gaps in priority order and wires coverage thresholds into
the harness so they can't silently regress.

---

## Current state (measured 2026-08-30)

| Layer | Files / tests | Line coverage | Enforced? |
|---|---|---|---|
| Python unit (`tests/`) | 76 files, 540 tests | 88% (v1) | No |
| Python unit (`v2/tests/`) | 20 files | not measured | No |
| API read-path e2e | `scripts/gate/bdd/` — 12 pytest-bdd scenarios + `acceptance.py` | read path only | Yes (`gate-verify`) |
| Schema fuzz | `scripts/gate/openapi.yaml` (Schemathesis) | API surface | On demand (`gate-fuzz`) |
| Frontend | — | **0%** | No |
| Write-path e2e | — | **none** | — |

### Worst pockets (unit coverage, `--show-missing`)

| File | Cov | Untested |
|---|---|---|
| `v1/api/tournament.py` | **0%** | whole handler — `/tournament/leaderboard` |
| `v1/tournament/scorer_lambda.py` | 39% | whole handler body (14–28) |
| `v1/tournament/variant_scorer.py` | 59% | `aggregate_variant_season()`, `get_leaderboard()` (102–150) |
| `v1/api/predictions.py` | 68% | retrospective join, odds join, **outlier calc** (66–160) |
| `scoring/metrics.py` | 77% | `aggregate_market_season()` (152–185) |
| `scrapers/weather/weather.py` | 70% | Open-Meteo fallback + BOM-outage paths (29–31, 51–53, 75–81) |
| `scoring/lambda_handler.py` | 72% | retrospective trigger + season-aggregation calls (108–137) |
| `v1/agent/graph.py` | 73% | `_extract_prediction_json` fallbacks, JSON-repair retry turn, budget-exceeded cached serve (211–309) |
| `v1/api/router.py` | 20% unit | rate-limit 429, `/accuracy` + `/tournament` dispatch, 404 (covered only by e2e) |

---

## Guardrails (apply to every phase)

- **TDD per `CLAUDE.md`:** write the failing test, commit it red, then the code
  (here the "code" is usually already written — commit the test, confirm it
  passes, and that it *fails* when you break the line it targets).
- Test files mirror source: `v1/api/tournament.py` → `tests/api/test_api_tournament.py`.
- AWS mocked with `moto` / `pytest-mock` — no real creds, no network.
- Fixtures in `tests/fixtures/`.
- Every phase ends green on `node ~/.claude/bin/gate-ci.mjs --force` before commit.

---

## Phase 1 — API layer (highest value, lowest effort)

The API is the only thing the frontend and the public consume. Three of its five
modules are effectively untested at the unit level.

### 1a. `tests/api/test_api_tournament.py` (new)
Covers `v1/api/tournament.py` end to end with a moto `variant_metrics` table:
- `VARIANT_METRICS_TABLE` unset → 503 `{"error": "Tournament not configured"}`.
- Seeded leaderboard → 200, body has `season` + `leaderboard`, sorted by pick
  rate, `Cache-Control: public, max-age=300`.
- `Decimal` values in the table serialise to JSON floats (`_serialise`).
- `?season=2025` query param honoured; absent → current UTC year.

### 1b. `tests/api/test_api_router.py` (new)
Unit-level coverage of `v1/api/router.py` dispatch (today only the e2e gate hits it):
- `/health` → 200 `{"status":"ok"}`.
- `/predictions/12`, `/accuracy`, `/tournament/leaderboard` each dispatch to the
  right sub-handler (assert via monkeypatched handler spies).
- Unknown path → 404.
- `RATE_LIMITS_TABLE` set + `check_rate_limit` returns `(False, reason)` → 429
  with `Retry-After: 3600`.
- `RATE_LIMITS_TABLE` unset → rate-limit check skipped (fail-open).
- `rawPath` vs legacy `path` key both resolved; trailing slash stripped.

### 1c. Extend `tests/api/test_api_predictions.py`
Add cases for the join branches currently only exercised e2e:
- Retrospective join: most-recent `generatedAt` wins; malformed retro row is
  swallowed (non-critical `except`), prediction still returned.
- Odds join + **`is_outlier`**: table-driven — agree on winner & margin ≤6 →
  `false`; disagree on winner → `true`; margin differs by >6 → `true`. Slug
  normalisation on both sides (`to_slug`).
- `ODDS_TABLE` / `RETROSPECTIVES_TABLE` / `RESULTS_TABLE` unset → response still
  200, those keys simply absent.
- Each optional table raising on `.scan` → swallowed, core prediction list intact.

### 1d. `tests/api/test_api_accuracy.py`
Close lines 11, 23 (missing-env / empty-metrics branches).

**Exit:** `v1/api/` package ≥ 95% line coverage.

---

## Phase 2 — Tournament scoring path

Round 25/26 showed this path silently producing 0 rows. It needs unit coverage
so a regression in aggregation maths is caught before a Sunday scorer run.

### 2a. `tests/tournament/test_scorer_lambda.py` (new)
- Happy path: seeded `simulation_predictions` + `results` + `variant_metrics`
  tables → handler returns `{"status":"ok","round":N,"variants_scored":M}`,
  calls `score_round` then `aggregate_variant_season`.
- Missing env var → `KeyError` surfaces (documents current contract).
- Empty round → `variants_scored: 0`, no metric writes.

### 2b. Extend `tests/tournament/test_variant_scorer.py`
- `aggregate_variant_season()`: two variants, mixed correct/incorrect, one
  unplayed match skipped; asserts `pick_rate`, `mean_margin_error`,
  `brier_score`, `rounds_active` written to the `{season}-season` period.
- Most-recent `scoredAt` wins when a match has duplicate result rows.
- `get_leaderboard()`: ranks by pick rate desc; empty table → `[]`;
  `Decimal` fields coerced.
- Confidence→probability fallback (`_CONFIDENCE_PROB.get(conf, 0.65)`) for an
  unknown confidence string.

### 2c. `tests/tournament/test_seed_variants.py`
Close the CLI-main / re-seed idempotency branch (132, 151, 160–169).

**Exit:** `v1/tournament/` package ≥ 90%; `variant_scorer.py` ≥ 95%.

---

## Phase 3 — Scoring + market aggregation

### 3a. Extend `tests/scoring/test_metrics.py`
- `aggregate_market_season()`: seeded `odds` + `results` → writes
  `market_pick_rate`, `market_mean_margin_error`, `market_brier_score` for the
  season period; dedupes to most-recent `scrapedAt` per match; no odds → early
  return, no writes; all matches unplayed → `score_market` raises, caught, total
  0 → early return.

### 3b. Extend `tests/scoring/test_scorer_lambda.py`
- Retrospective async-trigger branch (108–121): scoring a match invokes the
  retrospective Lambda (assert on a mocked `lambda:InvokeFunction`); invoke
  failure is swallowed.
- Season-aggregation calls fire once per handler run (129–137).
- Early-return branches (32–37) for a match with no prediction rows.

**Exit:** `scoring/` package ≥ 92%.

---

## Phase 4 — Scrapers (fallback + auth-failure paths)

These are the paths that broke live and had no test to catch them.

### 4a. `tests/scrapers/test_scraper_weather.py`
- Open-Meteo fallback when BOM returns non-200 / malformed geohash (29–31, 51–53).
- BOM 6-char-geohash truncation from a 7-char location result.
- Both providers failing → documented raise / empty return (75–81).

### 4b. `tests/scrapers/test_odds_lambda_handler.py`
- `the-odds-api.com` 401 `INVALID_KEY` → handler fails cleanly, writes nothing,
  returns a structured error (regression lock for the 2026-08-18 incident).
- Empty API response → no rows written, no crash.

### 4c. `tests/scrapers/test_scraper_articles.py`
Close `rss.py` 17–18, 37, 41–42 (feed fetch error, entry with no summary).

### 4d. `tests/scrapers/test_backfill.py`
Close `backfill.py` 41–43, 72–78 (dry-run branch, already-present skip).

**Exit:** every `scrapers/**` file ≥ 90%.

---

## Phase 5 — Agent graph (manual/backfill path)

Not on the automatic path since the 2026-08-23 cutover, but still the code that
serves manual backfill, and the JSON-repair logic has a documented failure mode.

### 5a. Extend `tests/agent/test_agent_graph.py`
- `_extract_prediction_json`: fenced ```json block; bare object in one text
  block; brace-span fallback across concatenated blocks; prose-only → `None`.
- JSON-repair retry: first stop returns prose → one follow-up turn with
  `_REPAIR_INSTRUCTION` → second turn returns valid JSON → success. Repair turn
  *also* prose → `FAILED` row written with `error: "Agent produced non-JSON..."`.
- Budget-exceeded at handler entry → cached prediction served with
  `staleness_flag: true`, Claude not called (assert 0 calls on the mock client).
- `_execute_tool` dispatch: unknown tool name → `ValueError`;
  `get_recent_form` receives the injected `exclude_match_id`.
- `_with_cache_breakpoint`: string content promoted to a block list; only the
  last block of the last message marked; empty message list is a no-op.

**Exit:** `v1/agent/graph.py` ≥ 90%.

---

## Phase 6 — Write-path boot-and-verify (structural)

`gate-verify` today boots only the API read path. Add a second acceptance
scenario group that exercises the async write path against DynamoDB Local, so
"orchestrator predicted a round end-to-end" becomes an executable claim (it is
currently only ever confirmed by eyeballing production after a Tuesday run).

### 6a. `scripts/gate/write_path_setup.py` (new)
Seeds a draw + team sheets into DynamoDB Local (no nrl.com fetch — inject a
fixture draw via the scraper's parse function, or stub the HTTP client).

### 6b. `scripts/gate/bdd/write_path.feature` (new)
- Invoke `v1.orchestrator.lambda_handler` in-process against the local tables →
  every match in the seeded draw gets one `predictions` row, `status: OK`,
  `prompt_version: stats-elo-v1`, `generation: 1`.
- Re-invoke → `generation: 2`, prior rows retained (supersede, not overwrite).
- `v1.orchestrator.coverage_check.lambda_handler` on a deliberately
  short-predicted round → emits `NrlPredictor/MissingPredictions` = shortfall,
  logs the missing matchIds. *(Also re-checks the still-open alarm-wiring gap
  from the incident section of `CLAUDE.md`.)*
- `scoring.lambda_handler` over the seeded round → `results` scored rows +
  `metrics` aggregation; retrospective Lambda invoked (mocked).

### 6c. Wire into `.claude/harness.json`
Extend the `acceptance` key so `gate-verify` runs read-path **and** write-path
scenarios. Keep them in separate feature files so a failure points at the right
half.

**Exit:** `gate-verify` green covering both paths; a broken orchestrator predict
loop fails the gate.

---

## Phase 7 — Frontend test infrastructure (greenfield)

No runner exists. Establish one, then cover the pure logic first (highest
value-per-line), then the components.

### 7a. Tooling
- Add **Vitest** + `@testing-library/react` + `@testing-library/jest-dom` +
  `jsdom` to `frontend/` dev deps. (Vitest over Jest: no Babel config, native
  ESM/TS, fast — matches the Next 16 / SWC setup.)
- `frontend/vitest.config.ts`, `frontend/vitest.setup.ts`.
- `package.json` scripts: `"test": "vitest run"`, `"test:watch": "vitest"`,
  `"test:cov": "vitest run --coverage"` (`@vitest/coverage-v8`).
- ESLint: allow `*.test.ts(x)` (test globals).

### 7b. `frontend/lib/*.test.ts` (pure functions — do these first)
- `teams.test.ts` — `toSlug` / `teamName` / display fallbacks across slug,
  nickname, full name, alias, unknown, `null`/`undefined`/`""`. Mirror the
  cases in the Python `tests/common/test_teams.py` so the two registries can't
  drift.
- `teamColors.test.ts` — known slug → colour pair; unknown → neutral default.
- `api.test.ts` — response shaping: `splitMatchId` strips `round-N-`; client
  sort by matchId; most-recent-generation selection; missing optional joins
  (`result`/`retrospective`/`odds`) tolerated; fetch non-200 → thrown/empty per
  current contract. Mock `fetch`.

### 7c. `frontend/components/*.test.tsx`
- `MatchCard.test.tsx` (247 lines, the richest) — renders predicted winner +
  margin + confidence; **outlier badge** shows only when `is_outlier`; result
  block only after the match is scored; retrospective section renders when
  present; team-colour accent applied.
- `RoundSelector.test.tsx` — options rendered, change fires navigation.
- `AccuracyCharts.test.tsx` — renders with a metrics fixture, empty state.

### 7d. Route-level smoke (optional, later)
Playwright against `next start` for `/`, `/predictions/[round]`, `/accuracy`,
`/tournament` — asserts SSR HTML is non-empty (guards the `output: 'export'` /
Tailwind-unprocessed classes of failure that have bitten before). Deferred
unless the component tests prove insufficient.

**Exit:** `frontend/lib` ≥ 90%, components ≥ 70%; `npm test` green.

---

## Phase 8 — Enforce coverage (make it a gate)

Without this, Phases 1–7 decay.

### 8a. Python
- Add `pytest-cov` to `[project.optional-dependencies].dev`.
- `pyproject.toml` `[tool.coverage.run]`: `source = ["common","scrapers","scoring","v1"]`,
  `branch = true`.
- `[tool.pytest.ini_options].addopts` gains
  `--cov --cov-report=term-missing --cov-fail-under=90`.
- Update `.claude/harness.json` `test` key to keep the coverage flags (they ride
  along on the existing `pytest` invocation, so `gate-ci` enforces the floor).
- Set the floor at the **current measured number, rounded down** (90), not an
  aspiration — ratchet up as phases land. Never lower it to make CI pass.

### 8b. Frontend
- `frontend/` `test:cov` with V8 provider, `--coverage.thresholds.lines=85`
  (lib) — start once Phase 7 lands.
- Add `cd frontend && npm run test` to `.claude/harness.json` `test` (or a new
  Stop-hook step) so the Python and JS suites both block turn-end.

### 8c. CI wiring note
`gate-ci` is the Stop hook. After 8a/8b it runs lint + typecheck + **both**
test suites with coverage floors. `gate-verify` (Phase 6) stays the boot gate.
No new CI system — just more teeth on the existing gates.

---

## Sequencing & effort

| Phase | Effort | Depends on | Coverage delta |
|---|---|---|---|
| 1 API | ~0.5 day | — | `v1/api` 59% → 95% |
| 2 Tournament scoring | ~0.5 day | — | `v1/tournament` 78% → 92% |
| 3 Scoring/market | ~0.5 day | — | `scoring` 82% → 92% |
| 4 Scrapers | ~0.5 day | — | `scrapers` → ≥90% each |
| 5 Agent graph | ~0.5 day | — | `graph.py` 73% → 90% |
| 6 Write-path e2e | ~1.5 days | — | new e2e layer |
| 7 Frontend | ~2 days | — | 0% → lib 90% / cmp 70% |
| 8 Enforce | ~0.5 day | 1–7 landing incrementally | ratchet |

Phases 1–5 are independent and can land in any order / in parallel — each is a
self-contained PR of new or extended test files with no production-code change
(except any genuine bug a new test uncovers, which becomes its own fix commit).
Phase 8a can land immediately at floor 90 and ratchet per phase.

**Recommended first PR:** Phase 1 + Phase 8a together — biggest coverage gain,
and it turns the floor on while the number is known-good.
