"""The fitted NFL SportModel and its prediction wrapper (common/nfl/model.py) —
spec criteria 2.8 and 2.9."""
from __future__ import annotations

import random

import pytest

from common.nfl.games import parse_csv
from common.nfl.model import NFL, predict_game
from common.stats_model.sport import NRL


@pytest.fixture
def by_id(sample_csv_text):
    games, _ = parse_csv(sample_csv_text)
    return {g.game_id: g for g in games}


def test_nfl_model_shape():
    assert NFL.margin_step == 1
    assert NFL.home_label == "Home-field"
    assert NFL.starting_rating == 1500.0
    assert 0.0 < NFL.season_regression < 1.0
    assert NFL.k_factor > 0 and NFL.home_advantage > 0
    assert 0.0 < NFL.medium_threshold < NFL.high_threshold < 0.5
    assert NFL != NRL


def test_neutral_game_is_predicted_with_zero_home_advantage(by_id):
    game = by_id["2025_01_KC_LAC"]
    assert game.neutral
    ratings = {"chargers": 1530.0, "chiefs": 1610.0}
    pred = predict_game(game, ratings, random.Random(1), n_simulations=4000)
    home_game = by_id["2025_01_DAL_PHI"]
    flipped = predict_game(
        home_game, {"eagles": 1530.0, "cowboys": 1610.0}, random.Random(1), n_simulations=4000
    )
    # Same ratings, same rng: only home advantage separates the two.
    assert pred.home_win_probability < flipped.home_win_probability
    assert any("Neutral site" in f for f in pred.key_factors)
    assert not any("advantage (+" in f for f in pred.key_factors)
    assert any(f.startswith("Home-field advantage (+") for f in flipped.key_factors)


@pytest.mark.parametrize("gap", [0.0, 40.0, 120.0, 300.0])
def test_nfl_prediction_never_says_home_ground_and_bands_are_ordered(by_id, gap):
    game = by_id["2025_01_DAL_PHI"]
    edges = []
    for seed in range(8):
        pred = predict_game(
            game, {"eagles": 1500.0 + gap, "cowboys": 1500.0}, random.Random(seed), n_simulations=1500
        )
        text = " ".join([*pred.key_factors, pred.reasoning])
        assert "Home ground" not in text
        assert "home-ground" not in text
        assert 0 <= pred.margin_low <= pred.margin_high
        edges += [pred.margin_low, pred.margin_high]
    assert any(e % 2 == 1 for e in edges)
