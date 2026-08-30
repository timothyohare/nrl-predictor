"""Tests for the shared stats-model prediction adapter (common/stats_model/predictor.py).

Extracted so the main predictions path (v1/orchestrator/stats_predictor.py, Phase 3
cutover) and the tournament variant (v1/tournament/stats_variant_runner.py, Phase 2)
compute predictions through one code path, not two that could drift. See
docs/plans/10-elo-monte-carlo-predictor.md.
"""
import random

import pytest

from common.stats_model.elo import DEFAULT_HOME_ADVANTAGE
from common.stats_model.predictor import predict_match


def test_predicted_winner_is_one_of_the_two_teams():
    ratings = {"panthers": 1500.0, "broncos": 1500.0}
    pred = predict_match("panthers", "broncos", ratings, DEFAULT_HOME_ADVANTAGE, 2000, random.Random(1))
    assert pred.predicted_winner in ("panthers", "broncos")


def test_favoured_home_team_is_predicted_to_win():
    ratings = {"panthers": 1700.0, "broncos": 1500.0}
    pred = predict_match("panthers", "broncos", ratings, DEFAULT_HOME_ADVANTAGE, 5000, random.Random(1))
    assert pred.predicted_winner == "panthers"
    assert pred.home_win_probability > 0.5


def test_predicted_margin_is_a_non_negative_int():
    ratings = {"panthers": 1500.0, "broncos": 1500.0}
    pred = predict_match("panthers", "broncos", ratings, DEFAULT_HOME_ADVANTAGE, 2000, random.Random(1))
    assert isinstance(pred.predicted_margin, int)
    assert pred.predicted_margin >= 0


def test_confidence_is_a_valid_level():
    ratings = {"panthers": 1500.0, "broncos": 1500.0}
    pred = predict_match("panthers", "broncos", ratings, DEFAULT_HOME_ADVANTAGE, 2000, random.Random(1))
    assert pred.confidence in ("LOW", "MEDIUM", "HIGH")


def test_key_factors_has_at_least_two_entries():
    # v1/agent/schema.py::validate_prediction requires len(key_factors) >= 2 —
    # this model's output must satisfy the same contract as the LLM's.
    ratings = {"panthers": 1500.0, "broncos": 1500.0}
    pred = predict_match("panthers", "broncos", ratings, DEFAULT_HOME_ADVANTAGE, 2000, random.Random(1))
    assert len(pred.key_factors) >= 2
    assert all(isinstance(f, str) and f for f in pred.key_factors)


def test_reasoning_is_a_non_empty_string():
    ratings = {"panthers": 1500.0, "broncos": 1500.0}
    pred = predict_match("panthers", "broncos", ratings, DEFAULT_HOME_ADVANTAGE, 2000, random.Random(1))
    assert isinstance(pred.reasoning, str) and pred.reasoning


def test_deterministic_given_same_seeded_rng():
    ratings = {"panthers": 1500.0, "broncos": 1500.0}
    first = predict_match("panthers", "broncos", ratings, DEFAULT_HOME_ADVANTAGE, 2000, random.Random(42))
    second = predict_match("panthers", "broncos", ratings, DEFAULT_HOME_ADVANTAGE, 2000, random.Random(42))
    assert first == second


@pytest.mark.parametrize("home_rating,away_rating", [(1650, 1500), (1500, 1650)])
def test_margin_magnitude_symmetric_regardless_of_which_side_is_favoured(home_rating, away_rating):
    ratings = {"panthers": home_rating, "broncos": away_rating}
    pred = predict_match("panthers", "broncos", ratings, 0, 8000, random.Random(11))
    assert pred.predicted_margin > 0


# --- Phase 1 plumbing (docs/plans/11-team-sheet-injury-weather-signals.md) ---
# `predict_match` gains optional rating-adjustment/variance-multiplier inputs
# that Phases 2-4 of plan 11 will wire real team-sheet/injury/weather signals
# into. Every test above passes none of them and must keep passing unchanged
# — that's the "no behavior change" contract for this phase.


def test_home_rating_adjustment_reduces_home_win_probability():
    ratings = {"panthers": 1600.0, "broncos": 1600.0}
    baseline = predict_match("panthers", "broncos", ratings, DEFAULT_HOME_ADVANTAGE, 5000, random.Random(3))
    penalized = predict_match(
        "panthers", "broncos", ratings, DEFAULT_HOME_ADVANTAGE, 5000, random.Random(3),
        home_rating_adjustment=-100.0,
    )
    assert penalized.home_win_probability < baseline.home_win_probability


def test_away_rating_adjustment_raises_home_win_probability_when_negative():
    ratings = {"panthers": 1600.0, "broncos": 1600.0}
    baseline = predict_match("panthers", "broncos", ratings, DEFAULT_HOME_ADVANTAGE, 5000, random.Random(3))
    penalized_away = predict_match(
        "panthers", "broncos", ratings, DEFAULT_HOME_ADVANTAGE, 5000, random.Random(3),
        away_rating_adjustment=-100.0,
    )
    assert penalized_away.home_win_probability > baseline.home_win_probability


def test_zero_adjustments_match_omitting_them_entirely():
    ratings = {"panthers": 1600.0, "broncos": 1550.0}
    explicit = predict_match(
        "panthers", "broncos", ratings, DEFAULT_HOME_ADVANTAGE, 3000, random.Random(5),
        home_rating_adjustment=0.0, away_rating_adjustment=0.0, margin_stdev_multiplier=1.0,
    )
    implicit = predict_match("panthers", "broncos", ratings, DEFAULT_HOME_ADVANTAGE, 3000, random.Random(5))
    assert explicit == implicit


def test_rating_adjustment_reflected_in_key_factors_and_reasoning():
    ratings = {"panthers": 1600.0, "broncos": 1600.0}
    pred = predict_match(
        "panthers", "broncos", ratings, DEFAULT_HOME_ADVANTAGE, 2000, random.Random(1),
        home_rating_adjustment=-25.0,
    )
    assert any("-25" in f for f in pred.key_factors)
    assert "No team-sheet, injury, weather" not in pred.reasoning


def test_no_adjustment_keeps_the_no_signal_disclaimer():
    ratings = {"panthers": 1500.0, "broncos": 1500.0}
    pred = predict_match("panthers", "broncos", ratings, DEFAULT_HOME_ADVANTAGE, 2000, random.Random(1))
    assert "No team-sheet, injury, weather" in pred.reasoning
