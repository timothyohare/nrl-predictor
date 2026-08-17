"""Elo rating core for the local predictor. See docs/plans/10-elo-monte-carlo-predictor.md.

Margin-of-victory multiplier follows the 538 NFL-Elo formula: bigger wins move
ratings further, with diminishing returns as the pre-match rating gap widens.
"""
from __future__ import annotations

import math

DEFAULT_K_FACTOR = 20.0
DEFAULT_HOME_ADVANTAGE = 55.0


def expected_score(rating_a: float, rating_b: float) -> float:
    """Probability that the side rated `rating_a` beats the side rated `rating_b`."""
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400.0))


def update_ratings(
    home_rating: float,
    away_rating: float,
    home_score: int,
    away_score: int,
    home_advantage: float = DEFAULT_HOME_ADVANTAGE,
    k_factor: float = DEFAULT_K_FACTOR,
) -> tuple[float, float]:
    """Post-match (home_rating, away_rating) after this result.

    `home_advantage` shapes the pre-match expectation (and therefore the size
    of the update) but is never added onto the returned ratings themselves.
    """
    home_effective = home_rating + home_advantage
    expected_home = expected_score(home_effective, away_rating)
    expected_away = 1.0 - expected_home

    margin = abs(home_score - away_score)
    if home_score > away_score:
        actual_home, actual_away = 1.0, 0.0
        winner_effective, loser_effective = home_effective, away_rating
    elif away_score > home_score:
        actual_home, actual_away = 0.0, 1.0
        winner_effective, loser_effective = away_rating, home_effective
    else:
        actual_home = actual_away = 0.5
        winner_effective = loser_effective = home_effective

    elo_diff = winner_effective - loser_effective
    multiplier = math.log(margin + 1) * (2.2 / (elo_diff * 0.001 + 2.2))

    home_new = home_rating + k_factor * multiplier * (actual_home - expected_home)
    away_new = away_rating + k_factor * multiplier * (actual_away - expected_away)
    return home_new, away_new
