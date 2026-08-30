# Plan: Elo + Monte Carlo Predictor (Anthropic-independent core)

## Goal

Build a fully local, deterministic prediction engine — Elo ratings with a
margin-of-victory update, fed into a Monte Carlo match simulation — that can
produce `predicted_winner`/`predicted_margin`/`confidence` without calling the
Anthropic API. Validate it offline against the 2026 season's actual results
before it touches any production path.

## Why This Matters

The current predictor (`v1/agent/graph.py`) is a Claude ReAct loop: every
prediction costs tokens, is subject to the 50K input-tokens/minute account
rate limit, and — as of 2026-08-16 — stops working entirely when the
Anthropic account runs out of credit (see CLAUDE.md "Pending verification").
A statistics-based core removes that single point of failure for the
numeric prediction (winner/margin/confidence), using data already sitting in
`results`/`teams`/team-sheets. It costs nothing per prediction and has no
external rate limit.

This does **not** replace the retrospective Lambda (Sonnet + Tavily search,
low volume, not on the rate-limited critical path) — out of scope for this
plan.

## Non-goals / open questions carried forward

- **Injury news / trap-game / coaching narrative signals are text-derived**
  and are not replaced here. Team-sheet *changes* (structured data — starting
  XIII diffs, spine positions 1/6/7/9 weighted higher) are in scope as a
  deterministic rating adjustment; RSS-article injury severity and
  narrative trap-game detection are not, pending a decision after backtest
  results are in. See `docs/plans/11-team-sheet-injury-weather-signals.md`
  (2026-08-26) for the follow-up plan covering team-sheet, injury, and
  weather signals.
- **Betting odds remain comparison-only.** The Elo/Monte Carlo model must
  never take `odds` table data as an input feature — same invariant as the
  agent (CLAUDE.md "Important constraints").
- Whether this becomes the *sole* predictor or one input to an ensemble is a
  decision for after Phase 1 (backtest) results are in — not fixed now.

## Data Model

No new scraping. New table: `team_ratings` (PK `teamId`, SK `season`) — one
current-rating row per team per season, written by the scoring Lambda
alongside the existing `scoring/metrics.py` aggregation step. Fields:
`rating` (float), `updated_at`, `matches_played`.

Inputs already available:
- `results` — chronological match outcomes (source of truth for rating updates and backtesting)
- `teams` (ladder) — points, for/against
- team sheets — starting XIII vs previous round, for missing-player penalties
- `weather` — temp/rain/wind, for total-score shading

## Design

### 1. Elo core (`common/stats_model/elo.py`)

- Standard Elo update: `new_rating = rating + K * (actual - expected)`,
  `expected = 1 / (1 + 10^((opponent_rating - rating) / 400))`
- Margin-of-victory multiplier (538 NFL-Elo style): scale `K` by
  `ln(margin + 1) * (2.2 / (rating_diff * 0.001 + 2.2))` so blowouts move
  ratings further than 2-point wins, with diminishing returns
- Fixed home-ground-advantage constant added to the home team's rating before
  computing `expected` (tunable; start at the commonly-used ~50-65 Elo points,
  calibrate in backtest)
- Season-boundary regression to the mean (out of scope until multi-season
  data exists — 2026 is the only season in the `results` table today)

### 2. Monte Carlo simulation (`common/stats_model/simulate.py`)

- `expected = 1 / (1 + 10^((away_rating - (home_rating + home_advantage)) / 400))`
  → home win probability
- Simulate N=10,000 matches: sample a margin from a distribution fit to
  historical `margin ~ rating_diff` (start with a Normal centered on a
  regression fit; revisit if backtest residuals look non-normal)
- Aggregate: win probability, expected margin, margin variance

### 3. Confidence calibration

- Bucket simulated win probability into LOW/MEDIUM/HIGH using thresholds
  fit against actual outcomes in the backtest, evaluated with the *same*
  confidence-calibration code already in `scoring/metrics.py`
  (`pick_rate_high_confidence` etc.) so results are directly comparable to
  the current LLM's calibration.

### 4. Templated reasoning/key_factors

- No LLM. `key_factors` = top 2-4 contributing terms by magnitude (rating
  diff, home advantage, recent form delta, H2H record, missing-player
  penalty). `reasoning` = a short templated sentence citing the same terms.
  The existing 200-400 word `reasoning` constraint was tuned for LLM output
  and should be relaxed for a templated predictor rather than padded.

## Implementation Steps

### Phase 1 — Offline backtest (this session)

#### 1. [SPIKE] `fetcher-spikes/elo_backtest_data_shape.py` — done

Pulled all `results` rows via `common.dynamo.scan_all`, deduped to one
canonical row per `matchId` (latest `scoredAt`). Findings:

- 315 deduped matches total, but only **92 use the round-qualified matchId**
  format (`round-<N>-...`), spanning rounds 12-24 — the current season's
  data since the round-qualification migration (`docs/matchid-identity-plan-v1.md`).
- The other 223 use the **legacy unqualified** `team-v-team` format from
  before that migration. Legacy ids are not round-qualified, so if the same
  two teams played twice in the season, the second result silently
  overwrites the first under the same matchId — no reliable way to recover
  which is which without the round-qualified migration being backfilled
  (out of scope here; that's `scripts/migrate_identity.py`'s job).
- No missing scores, no non-`FullTime` rows in the round-qualified set.

**Scope decision:** the Phase 1 backtest uses **only the 92 round-qualified
matches (rounds 12-24)**. It's a smaller sample than a full season, but it's
collision-free. Expanding to earlier rounds is blocked on the identity
migration, not on this plan.

#### 2. [TEST] `tests/common/test_elo.py`

- Elo update: winner's rating increases, loser's decreases, magnitudes are
  symmetric for a draw-probability-neutral case
- Margin-of-victory: a 40-point win moves rating further than a 2-point win,
  same starting ratings
- Home advantage: applied only to the home side's expected-score calculation,
  not persisted onto the rating itself
- Idempotency: replaying the same (winner, margin) update on a fresh pair of
  ratings is deterministic

#### 3. [CODE] `common/stats_model/elo.py`

Minimum code to pass the above — `EloRating` dataclass +
`update_ratings(home_rating, away_rating, home_score, away_score, home_advantage, k_factor) -> tuple[float, float]`.

#### 4. [TEST] `tests/common/test_simulate.py`

- Win probability is monotonic in rating difference
- Monte Carlo win-rate converges to the closed-form logistic probability
  within tolerance at N=10,000
- Margin distribution mean tracks the rating-diff-based expected margin

#### 5. [CODE] `common/stats_model/simulate.py`

Minimum code to pass the above.

#### 6. [CODE] `scripts/backtest_elo_model.py`

Walk `results` chronologically by round; for each match, predict using
ratings as they stood *before* that round (no look-ahead), score against the
actual outcome using the *same* `scoring/scorer.py` logic where possible,
then apply the update. Print pick_rate / mean_margin_error / Brier score for
the full backtest window, and print the same numbers for a rating-only
baseline (no home advantage) as a sanity check.

**Gate:** `pytest tests/common/test_elo.py tests/common/test_simulate.py -v`
green before moving to Phase 2. `.venv/bin/ruff check common/stats_model
scripts/backtest_elo_model.py` and `.venv/bin/mypy common/stats_model` clean.

### Phase 2 — Tournament variant — DEPLOYED 2026-08-17

Registered as variant `stats-elo-v1` in the existing prompt-tournament
infrastructure. Implementation:

- `common/match_id.py::teams_of()` — splits a matchId into (home, away)
  slugs (needed since this variant has no team-sheet/agent context to read
  teams from).
- `common/stats_model/ratings.py` — `load_canonical_results()` and
  `compute_ratings_as_of()` extracted from the backtest script into a
  shared module, so the offline backtest and the live variant run the exact
  same rating-replay code, not two implementations that could drift.
- `common/stats_model/confidence.py` — the Phase 1 calibrated thresholds,
  likewise extracted for reuse.
- `v1/tournament/stats_variant_runner.py` — runs the variant for a round.
  No persisted rating table: ratings are recomputed from `results` on every
  call (a full season is a few hundred matches — a walk-forward replay is
  effectively instant, and it avoids a rating-update hook wired into the
  scoring Lambda plus the risk of ratings drifting out of sync with
  `results`). Revisit only if this becomes a real cost/latency problem.
- `v1/tournament/worker_lambda.py` — dispatches on the variant's new
  `variant_type` field (`"stats_model"` vs the default `"prompt"` for the
  8 variants seeded before this field existed). The stats path skips the
  LLM rate-limit stagger entirely, since it makes no external API calls.
- `v1/tournament/seed_variants.py` — added `stats-elo-v1`, plus a `--only`
  flag so it could be seeded without re-versioning (and thus double-running)
  the 8 variants already live in production.

**Bug found and fixed along the way:** `run_variant_prediction()` never
wrote `roundNumber`/`season` onto `simulation_predictions` records, but
`variant_scorer.py`'s `score_round()`/`aggregate_variant_season()` filter on
exactly those fields — every variant's scoring would have silently produced
zero results forever. Undetected because the scorer's own tests seed
fixtures directly rather than going through the real writer. This would
have hit at the tournament's first live scored run (2026-08-21 per
CLAUDE.md's pending-verification note) — fixed for all 9 variants, not
just the new one.

**No CDK changes needed.** The worker Lambda already had `results` table
read access and `RESULTS_TABLE` in its environment (granted for the LLM
path's tools), and ships from the whole-repo code asset — `cdk deploy
NrlPredictorStack` picked up the new modules automatically. `cdk diff`
showed only Lambda code-content-hash churn (every function sharing the
asset) — no IAM, table, or route changes.

**Deploy steps taken:** `cdk deploy NrlPredictorStack` (61s, clean) →
`python3 -m v1.tournament.seed_variants --only stats-elo-v1` (dry-run
reviewed first; confirmed the other 8 variants' versions were untouched
before and after) → smoke-tested the deployed worker Lambda directly
(`nrl-predictor-tournament-worker`, bypassing the orchestrator) against the
already-completed `round-24-broncos-v-warriors`: correct pick (warriors),
predicted_margin=9 (actual 34 — normal variance, not a bug), 1.1s runtime,
clean CloudWatch logs, then deleted that manual test row so it doesn't
pollute the live season data ahead of the real automated run. Did **not**
invoke the live orchestrator — that would fan out real LLM calls to the 8
prompt variants, spending Anthropic credit with no visibility into the
current account balance after the 2026-08-16 outage. First real run is the
already-scheduled `nrl-tournament-saturday-am` cron, 2026-08-21 23:30 UTC.

**Verify after 2026-08-21:** `aws dynamodb scan --table-name
simulation_predictions --filter-expression "variantId = :v"
--expression-attribute-values '{":v":{"S":"stats-elo-v1"}}' --region
ap-southeast-2` should show one row per round-25(+) match, and after the
following Sunday scorer run, `variant_metrics` should carry a
`stats-elo-v1` row alongside the other 8 — compare its `pick_rate` against
theirs and the market baseline on the leaderboard (`/tournament/leaderboard`).

### Phase 3 — Production cutover — DEPLOYED 2026-08-23

Triggered early by the 2026-08-18 to -21 Anthropic credit exhaustion incident
(round 25 finished with 0/8 matches predicted — see CLAUDE.md's incident
section) rather than waiting for further live rounds of Phase 2 comparison.
Decision: **full replacement**, not fallback or ensemble — `v1/orchestrator`
no longer invokes the Claude agent at all.

- `common/stats_model/predictor.py` — new shared adapter,
  `predict_match(home, away, ratings, home_advantage, n_simulations, rng) ->
  StatsPrediction` (winner, margin, confidence, key_factors, reasoning).
  Extracted so the main path and the tournament variant compute a prediction
  through one code path — `v1/tournament/stats_variant_runner.py` refactored
  to call it too, rather than duplicating the Monte Carlo → winner/margin/
  confidence logic a second time.
- `v1/orchestrator/stats_predictor.py` — new `predict_round()`, called
  synchronously from `v1/orchestrator/lambda_handler.py` after the draw/team-
  sheet scrape. Computes ratings once per round (`compute_ratings_as_of`,
  no look-ahead) and writes directly to `predictions` — same schema shape as
  the old agent path (`status`, `staleness_flag`, `generation`, `key_factors`,
  `reasoning`, `data_freshness`), with `model_used`/`prompt_version` both set
  to `"stats-elo-v1"` so `scoring/metrics.py`'s prompt-version pick-rate
  bucketing keeps working unchanged.
- Removed: the async `agent_fn.invoke()` fan-out, the 8-15s inter-match
  stagger (no longer needed — no external API, no rate limit), and the
  `AGENT_FUNCTION_NAME`/`AGENT_INVOKE_STAGGER_SECONDS` orchestrator env vars.
  `infra/v1_stack.py`: `orchestrator_fn` lost its `agent_fn.grant_invoke`
  and gained `results_table.grant_read_data` +
  `predictions_table.grant_read_write_data`.
- `agent_fn` (the Claude ReAct Lambda) is **not deleted** — it stays deployed
  for manual/backfill invocation (`aws lambda invoke --function-name
  nrl-predictor-agent ...`), just no longer wired into the automatic
  per-round path. The retrospective Lambda (Sonnet + Tavily, low volume,
  scored-match analysis) is unaffected — out of scope, as originally noted
  above.
- Tests: `tests/common/test_predictor.py` (new), `tests/orchestrator/
  test_stats_predictor.py` (new), `tests/orchestrator/test_orchestrator.py`
  (rewritten — asserted agent-invoke behavior before, now asserts direct
  `predictions` writes), `tests/tournament/test_stats_variant_runner.py`
  (unchanged, still green after the refactor onto the shared adapter).
  `cdk synth NrlPredictorStack` clean; full gate (lint/typecheck/606
  tests/build) and `gate-verify` both green.

**Deployed to AWS 2026-08-23** — `cdk deploy` confirmed live: the orchestrator's
IAM policy no longer grants `lambda:InvokeFunction` on `AgentLambda`, and now
grants `predictions`/`results` table access instead. See CLAUDE.md for the
first live-round check (a full round predicted end-to-end via the new path,
not yet separately confirmed beyond the IAM/env verification above).

Also as of 2026-08-23: v2's automatic EventBridge schedules were paused
(`enabled=False`, not deleted) rather than cut over the same way — see
CLAUDE.md's incident section for why (v2's whole value is its 5-node LLM
pipeline, which has nothing distinct to offer without Claude).

## Success Criteria (Phase 1)

- Backtest runs end-to-end against the full 2026 `results` history with no
  look-ahead bugs (verified by the walk-forward test in the backtest script)
- Reports pick_rate / mean_margin_error / Brier score in the same units as
  `scoring/metrics.py`, so they're directly comparable to the season's
  62.6% LLM pick rate and the market baseline already tracked in the
  `metrics` table

## Phase 1 results (2026-08-17, `--n-simulations 10000 --seed 42`)

Backtest window: rounds 12-24, 92 round-qualified matches. All teams start at
a flat 1500 rating — round-12 form is not captured (no reliable per-team
history exists before this window; see the [SPIKE] note above).

| | pick_rate | mean_margin_error | brier_score |
|---|---|---|---|
| Elo + Monte Carlo, uncalibrated (home_advantage=55) | 0.6957 (64/92) | 12.45 | 0.2268 |
| Baseline: no home advantage | 0.5652 (52/92) | 12.76 | 0.2436 |
| Season LLM (`2026-season`, all rounds, API `/accuracy`) | 0.6327 (62/98) | 10.14 | 0.2313 |

Takeaways:
- The model **beats the season LLM pick rate** (69.6% vs 63.3%) on this
  window, on a flat `DEFAULT_HOME_ADVANTAGE = 55` and no per-team warm-up
  data. This is a strong first-pass signal, not a final verdict — 92
  matches is a small sample.
- **Margin prediction is worse than the LLM's** (12.45 vs 10.14 mean
  error) — expected from an uncalibrated margin model; addressed below.
- The no-home-advantage baseline confirms home advantage is doing real
  work (pick_rate drops 13 points without it) — sanity check passed.

## Phase 1 calibration (2026-08-17, same session)

Fit `simulate.py`'s margin distribution and `confidence_for()`'s thresholds
against this same 92-match window (still offline/local, no production path
touched):

**Margin model** — linear regression of `signed_margin ~ elo_diff`
(`elo_diff` = home_effective − away, i.e. including home advantage) over the
92 matches: `slope=0.0771`, `intercept=-3.86`, `residual_stdev=19.43`.
Replaced the placeholder `_BASE_MARGIN`/`_MARGIN_RATING_SCALE` constants in
`simulate.py` with this fit.

**Confidence thresholds** — computed win-probability distance from a
toss-up (`|p - 0.5|`) for all 92 matches and checked pick accuracy by
tercile: **60% → 73% → 75%** across increasing distance, confirming the
model's own confidence is meaningfully informative. But the distribution is
far more compressed than the placeholder thresholds assumed — max observed
distance was 0.326 (win prob 0.826), not the ~0.5 that thresholds tuned for
an LLM's confidence language implicitly assume. Refit `confidence_for()` to
the tercile boundaries: HIGH ≥ 0.12, MEDIUM ≥ 0.06, else LOW.

**Post-calibration result:**

| | pick_rate | mean_margin_error | brier_score |
|---|---|---|---|
| Elo + Monte Carlo, calibrated | 0.6957 (64/92) | 12.58 | **0.2188** |
| Season LLM | 0.6327 (62/98) | 10.14 | 0.2313 |

Brier improved (0.2268 → 0.2188) and is now clearly ahead of the season
LLM's 0.2313 — confidence calibration was the bigger lever than expected.
Pick rate is unchanged (confidence doesn't affect the winner pick). Margin
error is essentially flat (12.45 → 12.58) at this point — see the margin
model rework below, which fixed this properly.

## Margin model rework (2026-08-17, same session)

The signed-regression margin model above had a real bug, not just an
uncalibrated placeholder: `magnitude = |slope * elo_diff + intercept|`
fitted on *signed* margin doesn't vanish symmetrically when elo_diff flips
sign, because the intercept doesn't cancel under `abs()`. Concretely, "home
favoured by 20 Elo" and "home underdog by 20 Elo" got *different* predicted
margins (2.3 vs 5.4 points) purely from which side happened to be favoured —
there's no footy-shaped reason for that asymmetry; it's noise from a small
sample's intercept leaking into the win/loss-agnostic magnitude.

Checked empirically before touching code: fit `|margin| ~ |elo_diff|`
directly (unsigned regression, decoupled from Elo's win/loss sign, which
continues to drive `home_win_probability` unchanged) — `slope=0.0310`,
`intercept=12.19`, `residual_stdev=14.22` vs the old fit's stdev of 19.43.
In-sample MAE dropped from 11.7 to 10.4, essentially matching the season
LLM's 10.14. Also tried adding each team's rolling points-for/against
differential as a second regression feature (an attack/defense-style
signal, closer to a proper bivariate-Poisson scoring model) — SSE improved
only 1.7% and the added feature's sign was counter-intuitive, almost
certainly multicollinear noise with elo_diff at n=92. Not worth the added
state-tracking complexity; shelved, revisit if a future refit with more
data shows a real signal.

Added `tests/common/test_simulate.py::test_magnitude_symmetric_in_elo_diff_sign`
as a regression guard — asserts mirror-image matchups (favoured by X vs
underdog by X) produce the same `|expected_margin|` — then replaced
`simulate.py`'s magnitude formula with the unsigned fit.

**Post-rework result:**

| | pick_rate | mean_margin_error | brier_score |
|---|---|---|---|
| Elo + Monte Carlo, final | 0.6957 (64/92) | **11.96** | 0.2188 |
| Season LLM | 0.6327 (62/98) | 10.14 | 0.2313 |

Margin error down from 12.58 to 11.96 (in-sample MAE was 10.4; the gap is
Monte Carlo sampling noise on top of the fitted mean — the point estimate
itself, `magnitude_mean * sign`, is deterministic and equals the in-sample
fit). Now within ~1.8 points of the LLM's margin accuracy while still ahead
on pick_rate and Brier. Full repo: ruff/mypy/pytest all clean (557 tests).

**Next steps (not started):** margin error is close enough to the LLM now
that further gains have diminishing returns relative to effort — the
remaining known lever (attack/defense scoring features) needs more data
than 92 matches to separate from noise. Move to Phase 2 (tournament
variant) when ready to compare live rather than continuing to tune
offline against a fixed 92-match sample.
