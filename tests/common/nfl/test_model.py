"""The fitted NFL SportModel and its prediction wrapper (common/nfl/model.py) —
spec criteria 2.8 and 2.9."""
from __future__ import annotations

import random
import re
from collections import defaultdict

import pytest

from common.nfl.games import parse_csv
from common.nfl.model import NFL, predict_game
from common.stats_model.predictor import predict_match
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


def test_team_without_history_starts_at_the_starting_rating(by_id):
    """replay_ratings returns a defaultdict; a team absent from it (no played
    game yet) must predict from `starting_rating`, not raise KeyError."""
    game = by_id["2026_08_KC_DEN"]
    sparse = defaultdict(lambda: NFL.starting_rating, {game.home: 1600.0})
    explicit = {game.home: 1600.0, game.away: NFL.starting_rating}
    got = predict_game(game, sparse, random.Random(1), n_simulations=500)
    want = predict_game(game, explicit, random.Random(1), n_simulations=500)
    assert got == want


# ---------------------------------------------------------------------------
# Phase 5 final fixes: display names and "-0" in the human-readable text
# ---------------------------------------------------------------------------

def _words(text: str) -> set[str]:
    return set(re.findall(r"[A-Za-z0-9]+", text))


def test_nfl_text_uses_display_names_but_the_winner_stays_a_slug(by_id):
    game = by_id["2025_01_DAL_PHI"]
    pred = predict_game(
        game, {"eagles": 1580.0, "cowboys": 1500.0}, random.Random(1), n_simulations=1000
    )
    assert pred.predicted_winner == "eagles"
    words = _words(" ".join([*pred.key_factors, pred.reasoning]))
    assert {"Eagles", "Cowboys"} <= words
    assert not {"eagles", "cowboys"} & words
    assert pred.key_factors[0] == "Elo rating gap: Eagles 1580 vs Cowboys 1500 (+80)"
    assert pred.key_factors[1] == "Home-field advantage (+55 Elo) applied to Eagles"
    assert "picking Eagles by" in pred.reasoning


def test_nfl_model_labels_with_the_nfl_display_name():
    assert NFL.team_label("49ers") == "49ers"
    assert NFL.team_label("eagles") == "Eagles"


def test_team_label_defaults_to_identity_for_nrl():
    assert NRL.team_label("sea-eagles") == "sea-eagles"
    assert NRL.signed_int_text is False


@pytest.mark.parametrize("away", [1500.3, 1499.7, 1500.0])
def test_nfl_near_zero_elo_gap_is_plus_zero(by_id, away):
    game = by_id["2025_01_DAL_PHI"]
    pred = predict_game(game, {"eagles": 1500.0, "cowboys": away}, random.Random(1), n_simulations=500)
    assert pred.key_factors[0].endswith("(+0)")


def test_nfl_near_zero_rating_adjustments_never_read_minus_zero():
    pred = predict_match(
        "eagles", "cowboys", {"eagles": 1500.0, "cowboys": 1500.0}, NFL.home_advantage, 500,
        random.Random(1), home_rating_adjustment=-0.3, away_rating_adjustment=-12.6, model=NFL,
    )
    text = " ".join(pred.key_factors)
    assert "Eagles rating adjusted +0 ahead of kickoff" in text
    assert "Cowboys rating adjusted -13 ahead of kickoff" in text
    assert "-0" not in text
