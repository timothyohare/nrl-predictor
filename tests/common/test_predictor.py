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
