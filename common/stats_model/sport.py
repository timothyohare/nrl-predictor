"""Per-sport constants for the Elo + Monte Carlo core. See docs/plans/10-elo-monte-carlo-predictor.md
and the NFL predictor spec (.claude/sdlc/nfl-predictor/spec.md, Phase 1).

`update_ratings`, `simulate_match`, `confidence_for` and `predict_match` take an
optional `model: SportModel = NRL`, so another sport can reuse the same core with
its own fitted constants. `NRL` carries exactly the values the NRL path has always
used — every existing call site passes no `model` and is byte-identical
(tests/common/test_stats_model_nrl_golden.py is the proof). The old module-level
constants (`elo.DEFAULT_*`, `simulate._MARGIN_*`, `confidence._*_THRESHOLD`,
`ratings.STARTING_RATING`) stay as aliases of these fields.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


def _identity(slug: str) -> str:
    return slug


@dataclass(frozen=True)
class SportModel:
    k_factor: float
    home_advantage: float
    # |margin| = margin_slope * |elo_diff| + margin_intercept, residual stdev margin_stdev.
    margin_slope: float
    margin_intercept: float
    margin_stdev: float
    # Confidence buckets on |win_probability - 0.5|.
    high_threshold: float
    medium_threshold: float
    # Margin band snapping: 2 = even numbers (NRL), 1 = plain integers.
    margin_step: int
    # Rendered as "<home_label> advantage (+N Elo) applied to <team>" in key_factors.
    home_label: str
    # Fraction of each rating's distance from `starting_rating` removed at a season
    # boundary (0.0 = carry ratings over unchanged).
    season_regression: float
    starting_rating: float
    # Renders a team slug in key_factors/reasoning text only — never in
    # predicted_winner or any id. NRL keeps the identity (byte-identical text).
    team_label: Callable[[str], str] = _identity
    # Signed integers in key_factors via `round()` so a gap in (-0.5, 0) reads
    # "+0", not "-0". Off for NRL so its text stays byte-identical.
    signed_int_text: bool = False


# Fitted 2026-08-17 against the 92-match round-qualified backtest window (rounds
# 12-24, 2026 season) — see the per-module docstrings in elo.py / simulate.py /
# confidence.py for how each value was chosen.
NRL = SportModel(
    k_factor=20.0,
    home_advantage=55.0,
    margin_slope=0.0310,
    margin_intercept=12.19,
    margin_stdev=14.22,
    high_threshold=0.12,
    medium_threshold=0.06,
    margin_step=2,
    home_label="Home ground",
    season_regression=0.0,
    starting_rating=1500.0,
)
