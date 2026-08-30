# Implementation plan — Plan 12 test-coverage hardening

Execution companion to `docs/plans/12-test-coverage-hardening.md`. That doc holds
the rationale and the measured gap analysis; this doc is the build order, the
per-phase file list, and the exact verification commands. Progress is tracked in
`tasks/todo-12-test-coverage.md`.

## Ground rules

- **TDD-adjacent:** the production code already exists. For each target line,
  write the test that exercises it, confirm it passes, then confirm it *fails*
  when the target line is broken (mutation sanity-check). If a test uncovers a
  real bug, the fix is its own commit on the same branch, referenced in the PR.
- Test files mirror source: `v1/api/tournament.py` → `tests/api/test_api_tournament.py`.
- AWS is mocked with `moto` (`@mock_aws`) / `pytest-mock`. No real creds, no
  network. Follow the fixture style in `tests/api/test_api_predictions.py`.
- Fixtures live in `tests/fixtures/`.
- Each phase is its own branch + PR off `main`:
  `test/phase-<N>-<slug>`.
- Verification per phase, all must be green before commit:
  ```
  .venv/bin/ruff check <changed paths>
  .venv/bin/mypy <changed paths>
  AWS_DEFAULT_REGION=ap-southeast-2 AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test \
    .venv/bin/python -m pytest <new/changed test files> -q
  # then the full suite for regressions:
  AWS_DEFAULT_REGION=ap-southeast-2 AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test \
    .venv/bin/python -m pytest -q
  ```
- Commit trailer:
  ```
  Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01W7PN59ioLDVNdJMB3mybYj
  ```
- PR body ends with: `🤖 Generated with [Claude Code](https://claude.com/claude-code)`

## Coverage measurement

```
.venv/bin/coverage run --source=common,scrapers,scoring,v1 -m pytest tests -q
.venv/bin/coverage report --show-missing
```
Baseline (2026-08-30): **88%** total for v1.

---

## Phase 1 — API layer  ·  branch `test/phase-1-api`

Target: `v1/api/` package 59% → ≥95%.

**New `tests/api/test_api_tournament.py`** — covers `v1/api/tournament.py` (0% today):
- `VARIANT_METRICS_TABLE` unset → 503 `{"error":"Tournament not configured"}`.
- Seeded `variant_metrics` → 200; body has `season` + `leaderboard`; ordered by
  pick rate desc; header `Cache-Control: public, max-age=300`.
- `Decimal` cells serialise to JSON float via `_serialise`; a non-`Decimal`
  non-serialisable value raises `TypeError`.
- `queryStringParameters.season` honoured; absent → current UTC year.

**New `tests/api/test_api_router.py`** — covers `v1/api/router.py` dispatch (unit; today only e2e):
- `/health` → 200 `{"status":"ok"}`.
- `/predictions/12`, `/accuracy`, `/tournament/leaderboard` dispatch to the right
  sub-handler (monkeypatch each sub-handler with a spy, assert called once).
- Unknown path → 404 `{"error":"Not found"}`.
- `RATE_LIMITS_TABLE` set + `check_rate_limit` → `(False, reason)` → 429 with
  `Retry-After: 3600`, body `{"error": reason}`.
- `RATE_LIMITS_TABLE` unset → rate check skipped, request proceeds (fail-open).
- Legacy `event["path"]` resolves the same as `event["rawPath"]`; trailing
  slash stripped.

**Extend `tests/api/test_api_predictions.py`**:
- Retrospective join: newest `generatedAt` wins per match; a retro row that makes
  `.scan` raise is swallowed, predictions still returned.
- Odds join + `is_outlier` (table-driven): agree winner & |Δmargin|≤6 → `false`;
  disagree winner → `true`; |Δmargin|>6 → `true`. `to_slug` applied both sides.
- `ODDS_TABLE` / `RETROSPECTIVES_TABLE` / `RESULTS_TABLE` unset → 200, those keys
  simply absent from each prediction.

**Extend `tests/api/test_api_accuracy.py`**: cover lines 11, 23 (missing-env /
empty-metrics branches).

---

## Phase 2 — Tournament scoring  ·  branch `test/phase-2-tournament-scoring`

Target: `v1/tournament/` 78% → ≥92%; `variant_scorer.py` ≥95%.

**New `tests/tournament/test_scorer_lambda.py`** — covers `v1/tournament/scorer_lambda.py` (39%):
- Happy path: seeded `simulation_predictions` + `results` + `variant_metrics`;
  handler returns `{"status":"ok","round":N,"variants_scored":M}`; `score_round`
  then `aggregate_variant_season` both invoked (spy).
- Missing env var → `KeyError` (documents contract).
- Round with no sim rows → `variants_scored: 0`, no metric writes.

**Extend `tests/tournament/test_variant_scorer.py`** — covers `aggregate_variant_season()` + `get_leaderboard()` (102–150):
- Two variants, mixed correct/incorrect picks, one unplayed match skipped;
  asserts `pick_rate`, `mean_margin_error`, `brier_score`, `rounds_active`
  written to period `{season}-season`.
- Duplicate result rows per match → most-recent `scoredAt` used.
- `get_leaderboard()`: ranks by pick rate desc; empty table → `[]`; `Decimal`
  coerced to float.
- Unknown confidence string → `_CONFIDENCE_PROB.get(conf, 0.65)` fallback.

**Extend `tests/tournament/test_seed_variants.py`**: cover 132, 151, 160–169
(CLI `__main__` / re-seed idempotency skip).

---

## Phase 3 — Scoring + market aggregation  ·  branch `test/phase-3-scoring`

Target: `scoring/` 82% → ≥92%.

**Extend `tests/scoring/test_metrics.py`** — covers `aggregate_market_season()` (152–185):
- Seeded `odds` + `results` → writes `market_pick_rate`,
  `market_mean_margin_error`, `market_brier_score` for `{season}-season`.
- Dedup to most-recent `scrapedAt` per match.
- No odds rows → early return, zero writes.
- All matches unplayed (`score_market` raises, caught) → total 0 → early return.

**Extend `tests/scoring/test_scorer_lambda.py`** — covers `scoring/lambda_handler.py` (32–37, 108–137):
- Retrospective async-trigger branch: scoring a match invokes the retrospective
  Lambda (mock `lambda` client, assert `InvokeFunction`); invoke failure
  swallowed.
- Season-aggregation calls fire once per handler run.
- Match with no prediction rows → early-return branch, no scoring.

---

## Phase 4 — Scrapers  ·  branch `test/phase-4-scrapers`

Target: every `scrapers/**` file ≥90%.

**Extend `tests/scrapers/test_scraper_weather.py`** — `scrapers/weather/weather.py` (29–31, 51–53, 75–81):
- Open-Meteo fallback when BOM returns non-200 / malformed geohash.
- 7-char location result truncated to the 6-char BOM hourly geohash.
- Both providers failing → documented raise / empty return.

**Extend `tests/scrapers/test_odds_lambda_handler.py`** — regression lock for the 2026-08-18 incident:
- `the-odds-api.com` 401 `INVALID_KEY` → handler fails cleanly, writes nothing,
  returns a structured error (not a crash).
- Empty API response → no rows written, no exception.

**Extend `tests/scrapers/test_scraper_articles.py`**: `rss.py` 17–18, 37, 41–42
(feed-fetch error, entry with no `summary`).

**Extend `tests/scrapers/test_backfill.py`**: `backfill.py` 41–43, 72–78
(dry-run branch, already-present skip).

---

## Phase 5 — Agent graph  ·  branch `test/phase-5-agent-graph`

Target: `v1/agent/graph.py` 73% → ≥90%.

**Extend `tests/agent/test_agent_graph.py`**:
- `_extract_prediction_json`: fenced ```json block; bare object in a single text
  block; brace-span fallback across concatenated blocks; prose-only → `None`.
- JSON-repair retry: first stop = prose → one follow-up turn carrying
  `_REPAIR_INSTRUCTION` → second turn returns valid JSON → success. Repair turn
  also prose → caller writes the `FAILED` row (`error: "Agent produced non-JSON…"`).
- Budget exceeded at `lambda_handler` entry → cached prediction served with
  `staleness_flag: true`, mock Anthropic client called 0 times.
- `_execute_tool`: unknown tool name → `ValueError`; `get_recent_form` gets the
  injected `exclude_match_id=match_id`.
- `_with_cache_breakpoint`: string content promoted to a one-block list; only the
  final block of the final message marked `cache_control`; `[]` → no-op.

Use a fake Anthropic client (canned `messages.create` responses) — no network.

---

## Phase 6 — Write-path boot-and-verify  ·  branch `test/phase-6-write-path`

Owner: main session (structural, touches `.claude/harness.json`).

- **New `scripts/gate/write_path_setup.py`** — seed a draw + team sheets into
  DynamoDB Local from fixtures (no nrl.com fetch; feed the scraper parse
  functions fixture HTML/JSON, or stub `scrapers/shared/http_client`).
- **New `scripts/gate/bdd/write_path.feature`** + `test_write_path.py`:
  - Invoke `v1.orchestrator.lambda_handler` in-process against local tables →
    every drawn match gets one `predictions` row, `status: OK`,
    `prompt_version: stats-elo-v1`, `generation: 1`.
  - Re-invoke → `generation: 2`; generation-1 rows retained.
  - `v1.orchestrator.coverage_check.lambda_handler` on a deliberately
    under-predicted round → emits `NrlPredictor/MissingPredictions` = shortfall,
    logs missing matchIds. (Also probe the still-open alarm-wiring gap noted in
    `CLAUDE.md` — capture whether the metric datapoint actually lands.)
  - `scoring.lambda_handler` over the seeded round → `results` scored rows +
    `metrics` aggregation; retrospective Lambda invoke mocked and asserted.
- **`.claude/harness.json`**: extend `acceptance` so `gate-verify` runs the
  read-path *and* write-path features (separate files; a failure points at the
  right half).
- Verify: `node ~/.claude/bin/gate-verify.mjs` green (Docker required).

---

## Phase 7 — Frontend test infrastructure  ·  branch `test/phase-7-frontend`

Greenfield. Target: `frontend/lib` ≥90%, components ≥70%.

- **Tooling:** add dev deps `vitest`, `@vitest/coverage-v8`,
  `@testing-library/react`, `@testing-library/jest-dom`, `@testing-library/user-event`,
  `jsdom`. Add `frontend/vitest.config.ts` (jsdom env, setup file, coverage v8,
  `coverage.thresholds.lines` — lib 90) and `frontend/vitest.setup.ts`
  (`@testing-library/jest-dom`). `package.json` scripts: `test`, `test:watch`,
  `test:cov`. ESLint flat config: don't lint-error on test globals.
- **`frontend/lib/teams.test.ts`** — `toSlug` / `teamName` / display fallbacks
  across slug, nickname, full name, alias, unknown, `null`/`undefined`/`""`.
  Mirror `tests/common/test_teams.py` cases so the TS + Python registries can't
  drift.
- **`frontend/lib/teamColors.test.ts`** — known slug → colour pair; unknown →
  neutral default.
- **`frontend/lib/api.test.ts`** — `splitMatchId` strips `round-N-`; client-side
  sort by matchId; most-recent-generation selection; tolerates missing
  `result`/`retrospective`/`odds`; `fetch` non-200 → current contract
  (throw/empty). Mock `fetch`.
- **`frontend/components/MatchCard.test.tsx`** — predicted winner/margin/
  confidence render; outlier badge only when `is_outlier`; result block only
  after scored; retrospective section when present; team-colour accent applied.
- **`frontend/components/RoundSelector.test.tsx`**, **`AccuracyCharts.test.tsx`**
  — render with fixture + empty state; selector change fires navigation.
- Verify: `cd frontend && npm run lint && npm run typecheck && npm test`.

---

## Phase 8 — Enforce coverage  ·  branch `test/phase-8-enforce`

Owner: main session. Land **after** 1–7 merge.

- **Python:** add `pytest-cov` to `[project.optional-dependencies].dev`.
  `pyproject.toml`:
  - `[tool.coverage.run]` `source = ["common","scrapers","scoring","v1"]`,
    `branch = true`, `omit` test dirs.
  - `[tool.pytest.ini_options].addopts` += `--cov --cov-report=term-missing
    --cov-fail-under=90` (set to the measured post-merge number, rounded down —
    never below what's achieved; ratchet up only).
- **`.claude/harness.json`:** keep the cov flags on the `test` key; add
  `cd frontend && npm run test` so both suites block turn-end via `gate-ci`.
- **Frontend:** `test:cov` V8 thresholds (lib 90). Wire into the harness `test`.
- Verify: `node ~/.claude/bin/gate-ci.mjs --force --full` green; deliberately
  drop a covered line → gate reds.

---

## Merge order

1. Phase 8a (`pytest-cov` wired at floor 90) can land first or alongside Phase 1.
2. Phases 1–5, 7 independent — merge in any order as each PR goes green.
3. Phase 6 independent of 1–5/7 but needs Docker for its gate.
4. Final Phase 8 pass ratchets `--cov-fail-under` to the achieved number and
   turns on the frontend floor, once 1–7 are in.
