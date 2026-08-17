"""Monte Carlo match simulation on top of Elo ratings. See docs/plans/10-elo-monte-carlo-predictor.md.

Win/loss is drawn from the closed-form Elo expected score directly (so the
simulated win rate is an unbiased estimator of it, not an approximation
derived from a separately-fit margin distribution). Margin *magnitude* is a
linear fit of `|margin| ~ |elo_diff|` (elo_diff = home_effective - away,
i.e. including home advantage) against the 92-match round-qualified
backtest window in `results` (rounds 12-24, 2026 season) — see
docs/plans/10-elo-monte-carlo-predictor.md, Phase 1 margin calibration.

Deliberately fit on the *unsigned* margin against the *unsigned* rating gap,
not `signed_margin ~ elo_diff`: a signed fit's intercept doesn't vanish when
you flip the sign of elo_diff and take abs(), so it silently predicts a
different typical margin for "home favoured by X" than "home underdog by X"
— a sign-dependent asymmetry with no footy-shaped justification, and it
measurably fit worse (MAE 11.7 vs 10.4 on the same data). Fitting on
magnitude directly removes the asymmetry by construction and improved the
fit. Refit when enough post-round-24 data accumulates to widen the sample.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from common.stats_model.elo import expected_score

# Fitted 2026-08-17 against rounds 12-24 (n=92): |margin| = _MARGIN_SLOPE *
# |elo_diff| + _MARGIN_INTERCEPT, residual stdev _MARGIN_STDEV. See scripts/backtest_elo_model.py.
_MARGIN_SLOPE = 0.0310
_MARGIN_INTERCEPT = 12.19
_MARGIN_STDEV = 14.22


@dataclass
class SimulationResult:
    home_win_probability: float
    expected_margin: float
    n: int


def simulate_match(
    home_rating: float,
    away_rating: float,
    home_advantage: float,
    n: int,
    rng: random.Random,
) -> SimulationResult:
    """Simulate `n` matches between two Elo-rated teams.

    `expected_margin` is signed from the home team's perspective (positive =
    home favoured to win by that many points).
    """
    home_effective = home_rating + home_advantage
    p_home = expected_score(home_effective, away_rating)
    elo_diff = home_effective - away_rating
    magnitude_mean = max(1.0, _MARGIN_SLOPE * abs(elo_diff) + _MARGIN_INTERCEPT)

    home_wins = 0
    margin_total = 0.0
    for _ in range(n):
        is_home_win = rng.random() < p_home
        magnitude = max(1.0, rng.gauss(magnitude_mean, _MARGIN_STDEV))
        margin_total += magnitude if is_home_win else -magnitude
        if is_home_win:
            home_wins += 1

    return SimulationResult(
        home_win_probability=home_wins / n,
        expected_margin=margin_total / n,
        n=n,
    )
