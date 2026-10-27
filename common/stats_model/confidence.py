"""Confidence bucketing for the stats model. See docs/plans/10-elo-monte-carlo-predictor.md
Phase 1 calibration.

Thresholds fitted 2026-08-17 against the 92-match round-qualified backtest window
(rounds 12-24, 2026 season): tercile boundaries of |win_probability - 0.5| that
produced monotonically increasing pick accuracy (60% -> 73% -> 75% low/medium/high).
This model's probabilities are far more compressed than a hand-picked "sports
betting intuition" threshold assumes — the observed max distance from a toss-up
was 0.326, not ~0.5. Refit alongside the margin model as more data accumulates.
"""
from __future__ import annotations

from common.stats_model.sport import NRL, SportModel

# Aliases of the NRL SportModel, kept for existing call sites.
_HIGH_THRESHOLD = NRL.high_threshold
_MEDIUM_THRESHOLD = NRL.medium_threshold


def confidence_for(win_probability: float, *, model: SportModel = NRL) -> str:
    """HIGH/MEDIUM/LOW bucket for a simulated home-win probability."""
    distance_from_toss_up = abs(win_probability - 0.5)
    if distance_from_toss_up >= model.high_threshold:
        return "HIGH"
    if distance_from_toss_up >= model.medium_threshold:
        return "MEDIUM"
    return "LOW"
