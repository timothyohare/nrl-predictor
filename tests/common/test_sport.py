"""Tests for the per-sport model adapter (common/stats_model/sport.py).

NFL predictor spec (.claude/sdlc/nfl-predictor/spec.md), Phase 1: the Elo + Monte
Carlo core takes an optional `model: SportModel = NRL`, so a second sport can reuse
it with its own constants while every NRL call site stays byte-identical (the
golden snapshot in test_stats_model_nrl_golden.py is the proof for the default
path; this file pins the explicit-`NRL` path and the non-NRL knobs).
"""
from __future__ import annotations

import dataclasses
import json
import random
from dataclasses import dataclass
from pathlib import Path

import pytest

from common.stats_model import confidence, elo, ratings, simulate
from common.stats_model.confidence import confidence_for
from common.stats_model.elo import update_ratings
from common.stats_model.predictor import predict_match
from common.stats_model.ratings import compute_ratings_as_of, replay_ratings
from common.stats_model.simulate import simulate_match
from common.stats_model.sport import NRL, SportModel

GOLDEN = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "stats_model_nrl_golden.json").read_text()
)


# ---------------------------------------------------------------------------
# 1.3 — NRL carries today's constants exactly
# ---------------------------------------------------------------------------

def test_nrl_constants_are_todays_values():
    assert NRL.k_factor == 20.0
    assert NRL.home_advantage == 55.0
    assert (NRL.margin_slope, NRL.margin_intercept, NRL.margin_stdev) == (0.0310, 12.19, 14.22)
    assert (NRL.high_threshold, NRL.medium_threshold) == (0.12, 0.06)
    assert NRL.margin_step == 2
    assert NRL.season_regression == 0.0
    assert NRL.home_label == "Home ground"
    assert NRL.starting_rating == 1500.0


def test_module_constants_stay_as_aliases_of_nrl():
    assert elo.DEFAULT_K_FACTOR == NRL.k_factor
    assert elo.DEFAULT_HOME_ADVANTAGE == NRL.home_advantage
    assert simulate._MARGIN_SLOPE == NRL.margin_slope
    assert simulate._MARGIN_INTERCEPT == NRL.margin_intercept
    assert simulate._MARGIN_STDEV == NRL.margin_stdev
    assert confidence._HIGH_THRESHOLD == NRL.high_threshold
    assert confidence._MEDIUM_THRESHOLD == NRL.medium_threshold
    assert ratings.STARTING_RATING == NRL.starting_rating


def test_sport_model_is_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        NRL.k_factor = 99.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 1.2 — passing model=NRL explicitly is identical to the default call
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("case", GOLDEN["predict_match"], ids=lambda c: f"seed{c['inputs']['seed']}")
def test_predict_match_explicit_nrl_matches_default(case):
    i = case["inputs"]

    def run(**model_kw):
        return predict_match(
            i["home"], i["away"], i["ratings"], i["home_advantage"], i["n_simulations"],
            random.Random(i["seed"]),
            home_rating_adjustment=i["home_rating_adjustment"],
            away_rating_adjustment=i["away_rating_adjustment"],
            margin_stdev_multiplier=i["margin_stdev_multiplier"],
            **model_kw,
        )

    explicit = dataclasses.asdict(run(model=NRL))
    assert explicit == dataclasses.asdict(run())
    assert explicit == case["expected"]


@pytest.mark.parametrize("case", GOLDEN["simulate_match"], ids=lambda c: f"seed{c['inputs']['seed']}")
def test_simulate_match_explicit_nrl_matches_default(case):
    i = case["inputs"]

    def run(**model_kw):
        return simulate_match(
            i["home_rating"], i["away_rating"], i["home_advantage"], i["n"],
            random.Random(i["seed"]), margin_stdev_multiplier=i["margin_stdev_multiplier"],
            **model_kw,
        )

    explicit = dataclasses.asdict(run(model=NRL))
    assert explicit == dataclasses.asdict(run())
    assert explicit == case["expected"]


@pytest.mark.parametrize("case", GOLDEN["update_ratings"])
def test_update_ratings_explicit_nrl_matches_default(case):
    i = case["inputs"]
    args = (i["home_rating"], i["away_rating"], i["home_score"], i["away_score"])
    kw = {"home_advantage": i["home_advantage"], "k_factor": i["k_factor"]}
    assert update_ratings(*args, **kw, model=NRL) == update_ratings(*args, **kw)
    assert list(update_ratings(*args, **kw, model=NRL)) == case["expected"]


@pytest.mark.parametrize("case", GOLDEN["confidence_for"])
def test_confidence_for_explicit_nrl_matches_default(case):
    p = case["inputs"]["win_probability"]
    assert confidence_for(p, model=NRL) == confidence_for(p) == case["expected"]


def test_compute_ratings_as_of_unchanged():
    """`compute_ratings_as_of` keeps its signature (no model arg) and semantics."""
    block = GOLDEN["compute_ratings_as_of"]
    for case in block["cases"]:
        i = case["inputs"]
        out = compute_ratings_as_of(block["results"], i["before_round"], i["home_advantage"])
        assert dict(out) == case["expected"]


# ---------------------------------------------------------------------------
# The model's constants actually drive each function
# ---------------------------------------------------------------------------

def test_update_ratings_defaults_come_from_the_model():
    other = dataclasses.replace(NRL, k_factor=40.0, home_advantage=0.0)
    assert update_ratings(1500.0, 1500.0, 24, 12, model=other) == update_ratings(
        1500.0, 1500.0, 24, 12, home_advantage=0.0, k_factor=40.0
    )


def test_update_ratings_explicit_args_override_the_model():
    other = dataclasses.replace(NRL, k_factor=40.0, home_advantage=0.0)
    assert update_ratings(
        1500.0, 1500.0, 24, 12, home_advantage=55.0, k_factor=20.0, model=other
    ) == update_ratings(1500.0, 1500.0, 24, 12)


def test_simulate_match_uses_the_model_margin_fit():
    wide = dataclasses.replace(NRL, margin_intercept=30.0)
    base = simulate_match(1500.0, 1500.0, 55.0, 2000, random.Random(1))
    shifted = simulate_match(1500.0, 1500.0, 55.0, 2000, random.Random(1), model=wide)
    assert shifted.home_win_probability == base.home_win_probability
    assert shifted.winning_margin_mean > base.winning_margin_mean + 10


def test_confidence_for_uses_the_model_thresholds():
    strict = dataclasses.replace(NRL, high_threshold=0.3, medium_threshold=0.2)
    assert confidence_for(0.65) == "HIGH"
    assert confidence_for(0.65, model=strict) == "LOW"
    assert confidence_for(0.75, model=strict) == "MEDIUM"
    assert confidence_for(0.85, model=strict) == "HIGH"


# ---------------------------------------------------------------------------
# 1.4 — integer margin step and sport-specific home label
# ---------------------------------------------------------------------------

_INTEGER_MODEL = dataclasses.replace(NRL, margin_step=1, home_label="Home-field advantage")


def _integer_predictions():
    rs = {"chiefs": 1560.0, "raiders": 1480.0}
    return [
        predict_match("chiefs", "raiders", rs, 48.0, 2000, random.Random(seed), model=_INTEGER_MODEL)
        for seed in range(12)
    ]


def test_integer_margin_step_allows_odd_band_edges():
    preds = _integer_predictions()
    edges = [p.margin_low for p in preds] + [p.margin_high for p in preds]
    assert all(isinstance(e, int) for e in edges)
    assert any(e % 2 == 1 for e in edges)
    assert all(0 <= p.margin_low <= p.margin_high for p in preds)


def test_custom_home_label_replaces_home_ground():
    for pred in _integer_predictions():
        assert not any("Home ground" in f for f in pred.key_factors)
        assert any("Home-field advantage" in f for f in pred.key_factors)


# ---------------------------------------------------------------------------
# 1.5 — generic replay_ratings
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _Game:
    home: str
    away: str
    home_score: int | None
    away_score: int | None
    season: int
    week: int
    neutral: bool = False


def test_replay_neutral_game_uses_zero_home_advantage():
    out = replay_ratings([_Game("chiefs", "raiders", 27, 20, 2025, 1, neutral=True)], NRL)
    expected = update_ratings(1500.0, 1500.0, 27, 20, home_advantage=0.0, k_factor=NRL.k_factor)
    assert (out["chiefs"], out["raiders"]) == expected


def test_replay_home_game_uses_the_model_home_advantage():
    out = replay_ratings([_Game("chiefs", "raiders", 27, 20, 2025, 1)], NRL)
    expected = update_ratings(1500.0, 1500.0, 27, 20, home_advantage=NRL.home_advantage)
    assert (out["chiefs"], out["raiders"]) == expected


def test_replay_regresses_toward_start_at_each_season_boundary():
    model = dataclasses.replace(NRL, season_regression=1 / 3)
    season_one = [
        _Game("chiefs", "raiders", 40, 3, 2024, 1),
        _Game("bills", "chiefs", 10, 31, 2024, 2),
    ]
    end_of_one = replay_ratings(season_one, model)
    regressed = {t: 1500.0 + (r - 1500.0) * 2 / 3 for t, r in end_of_one.items()}

    # Ratings going into the new season's first week are regressed...
    first_game = _Game("raiders", "bills", 17, 14, 2025, 1)
    at_boundary = replay_ratings([*season_one, first_game], model, before=(2025, 1))
    assert dict(at_boundary) == pytest.approx(regressed)

    # ...and the new season's first game is applied on top of the regressed ratings.
    after = replay_ratings([*season_one, first_game], model)
    expected = update_ratings(
        regressed["raiders"], regressed["bills"], 17, 14, model=model
    )
    assert (after["raiders"], after["bills"]) == pytest.approx(expected)
    assert after["chiefs"] == pytest.approx(regressed["chiefs"])


def test_replay_without_regression_carries_ratings_across_seasons():
    games = [_Game("chiefs", "raiders", 40, 3, 2024, 1)]
    assert dict(replay_ratings(games, NRL, before=(2025, 1))) == dict(replay_ratings(games, NRL))


def test_replay_before_excludes_games_at_or_after_the_cutoff():
    early = _Game("chiefs", "raiders", 27, 20, 2025, 1)
    cut = _Game("raiders", "chiefs", 35, 0, 2025, 2)
    later = _Game("bills", "chiefs", 3, 50, 2025, 3)
    out = replay_ratings([early, cut, later], NRL, before=(2025, 2))
    assert dict(out) == dict(replay_ratings([early], NRL))

    # No look-ahead: rewriting a cut-off-or-later score changes nothing.
    rewritten = dataclasses.replace(cut, home_score=0, away_score=60)
    assert dict(replay_ratings([early, rewritten, later], NRL, before=(2025, 2))) == dict(out)


def test_replay_skips_unplayed_games():
    played = _Game("chiefs", "raiders", 27, 20, 2025, 1)
    unplayed = _Game("bills", "chiefs", None, None, 2025, 2)
    assert dict(replay_ratings([played, unplayed], NRL)) == dict(replay_ratings([played], NRL))


def test_replay_tie_scores_both_sides_half():
    """A tie is fed to update_ratings as equal scores (0.5 actual each side).

    Note: under the NRL margin-of-victory multiplier, log(margin + 1) is 0 for a
    0-point margin, so a tie leaves both ratings where they were.
    """
    out = replay_ratings([_Game("chiefs", "raiders", 20, 20, 2025, 1)], NRL)
    assert (out["chiefs"], out["raiders"]) == update_ratings(1500.0, 1500.0, 20, 20)


def test_replay_unseen_team_starts_at_model_starting_rating():
    model = dataclasses.replace(NRL, starting_rating=1000.0)
    assert replay_ratings([], model)["chiefs"] == 1000.0


def test_replay_sorts_games_chronologically():
    a = _Game("chiefs", "raiders", 27, 20, 2025, 1)
    b = _Game("raiders", "chiefs", 35, 0, 2025, 2)
    assert dict(replay_ratings([b, a], NRL)) == dict(replay_ratings([a, b], NRL))


def test_sport_model_is_constructible_for_another_sport():
    model = SportModel(
        k_factor=20.0, home_advantage=48.0,
        margin_slope=0.04, margin_intercept=8.0, margin_stdev=13.0,
        high_threshold=0.2, medium_threshold=0.1,
        margin_step=1, home_label="Home-field", season_regression=1 / 3,
        starting_rating=1500.0,
    )
    assert model.margin_step == 1
