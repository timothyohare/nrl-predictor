# Plan: Margin Range Band for stats-elo-v1

## Goal

Stop presenting the predicted margin as a single point estimate. Show an
honest range instead ("Panthers by 4–18"), derived from the Monte Carlo
simulation the `stats-elo-v1` predictor (`common/stats_model/`, see
`docs/plans/10-elo-monte-carlo-predictor.md`) already runs.

## Why This Matters

Round 27 surfaced the problem: predicted margins of **11** (Dolphins v Titans)
and **13** (Warriors v Sea Eagles).

NRL scoring is almost entirely even-valued — try 4, converted try 6, penalty
goal 2, conversion 2; only a field goal (1, rare) is odd. So the difference
between two final scores is *almost always even*. A point estimate of 11 or 13
implies a lone field goal decided the match — a low-probability outcome to
present as the headline number.

Deeper than the odd/even tell: `predicted_margin` is
`round(abs(expected_margin))`, a real-valued output rounded to the nearest
integer. It carries false precision the Elo + Monte Carlo calculation doesn't
actually have — the model's own margin residual stdev is ~14 points
(`_MARGIN_STDEV = 14.22`, fitted rounds 12–24).

## Options Considered

The original addendum (`NRL_Predictor_Margin_Range_Fix.md`) weighed three:

- **A — snap to nearest even.** Five-minute fix, still a false-precision point.
- **B — snap to historical margin distribution.** Needs scraped history, still
  a single number.
- **C — report a range.** Chosen. A range doesn't imply the precision a single
  number does, and sidesteps odd/even entirely.

## Divergence from the addendum's Option C implementation

The addendum sketched Option C as: accumulate `predicted_margin` vs
`actual_margin` history from the `results` table, compute a standard deviation
from it, fall back to a flat ~13 until enough rounds are banked (an
acknowledged cold-start problem).

**We didn't need any of that.** The addendum's premise — *"ELO produces a win
probability, not directly a distribution of margins"* — isn't true for this
codebase. `simulate_match()` runs 10,000 Monte Carlo trials and produces a
full margin distribution per match. So:

- The band is read straight off the simulated margins. **No history to
  accumulate, no cold-start fallback.**
- The addendum's fallback constant (~13) is already in the model as
  `_MARGIN_STDEV = 14.22`, fitted against real results. The addendum's
  "replace the flat fallback with a real calculation" follow-up is
  effectively already done.

## Implementation

### `common/stats_model/simulate.py`

`SimulationResult` gains two fields:

- `winning_margin_mean` — mean of the trial margin **conditioned on the
  predicted side winning**. Unlike `expected_margin` (which averages in the
  upset trials and is regressed toward zero), this is "if they win, by roughly
  this much". It shifts up with the rating gap.
- `margin_stdev` — stdev of that same winner-conditioned margin. Conditioning
  on the winner keeps it a clean one-lobe distribution (~= the margin model's
  residual stdev), rather than a bimodal signed quantity whose spread is
  dominated by how far apart the win/loss lobes sit.

Both are accumulated in the existing trial loop (running sum + sum of squares),
so no second pass and the rng call sequence is unchanged — determinism holds.
The `margin_stdev_multiplier` weather signal flows through automatically
(it already scales `magnitude_stdev`).

### `common/stats_model/predictor.py`

`StatsPrediction` gains `margin_low: int`, `margin_high: int`:

```
margin_low  = round_to_even(max(winning_margin_mean - margin_stdev, 0.0))
margin_high = round_to_even(winning_margin_mean + margin_stdev)
```

- Centred on `winning_margin_mean`, ±1 SD — the band chosen (see
  `AskUserQuestion` in the implementing session: "from the Monte Carlo
  distribution", "point estimate ± 1 std dev").
- `round_to_even(x) = int(2 * round(x / 2))` — NRL margins are even-biased.
- Low clamps at 0 (a margin can't be negative); reachable in practice only
  when the weather variance multiplier widens one SD past the mean.
- The band shifts with the matchup (bigger rating gap lifts both ends) while
  staying ~2 SD wide.

`predicted_margin` is unchanged — still `round(abs(expected_margin))`, still
persisted, still what scoring/metrics grade against. It is the internal point
estimate; it is not displayed as a standalone figure any more.

### `v1/orchestrator/stats_predictor.py`

Writes `margin_low` / `margin_high` onto the `predictions` row alongside
`predicted_margin`.

### `v1/api/predictions.py`

No change — the handler passes the whole DynamoDB item through, so the two new
fields reach the response for free (test added to lock that in).

### `frontend/lib/api.ts` + `frontend/components/MatchCard.tsx`

`Prediction` gains optional `margin_low` / `margin_high`. `MatchCard` renders
"BY 4–18" when both are present and `high > low`, and falls back to
`predicted_margin` for older rows and the manual agent path (which have no
band). The post-result "✗ margin (±n)" indicator still compares against the
point estimate.

## Follow-up / Not Yet Done

- **Score against the range.** The accuracy dashboard and `scoring/scorer.py`
  still grade the point estimate only. Consider scoring a prediction as
  "correct" when the actual margin falls inside `[margin_low, margin_high]`,
  in addition to (or instead of) the point-estimate margin error. This
  touches the `metrics` table and the accuracy page — deliberately deferred.
- **Tournament parity.** `v1/tournament/stats_variant_runner.py` calls the same
  `predict_match()` but doesn't persist the band (it scores on the point
  estimate). Add it if the tournament ever displays a range.
- **Manual agent path.** `v1/agent/` predictions have no band; the frontend
  falls back cleanly. No plan to add one unless the agent path returns to the
  automatic schedule.
