"""Tests for the Elo rating core (common/stats_model/elo.py). See docs/plans/10."""
import pytest

from common.stats_model.elo import (
    DEFAULT_HOME_ADVANTAGE,
    DEFAULT_K_FACTOR,
    expected_score,
    update_ratings,
)


def test_expected_score_equal_ratings_is_half():
    assert expected_score(1500, 1500) == pytest.approx(0.5)


def test_expected_score_favours_higher_rating():
    assert expected_score(1600, 1500) > 0.5
    assert expected_score(1500, 1600) < 0.5


def test_expected_score_symmetric():
    assert expected_score(1600, 1500) == pytest.approx(1 - expected_score(1500, 1600))


def test_update_ratings_winner_gains_loser_loses():
    home_new, away_new = update_ratings(1500, 1500, home_score=24, away_score=10, home_advantage=0)
    assert home_new > 1500
    assert away_new < 1500


def test_update_ratings_zero_sum_without_home_advantage():
    # With no home advantage the pre-match expectation is symmetric, so the
    # winner's gain equals the loser's loss.
    home_new, away_new = update_ratings(1500, 1500, home_score=24, away_score=10, home_advantage=0)
    assert (home_new - 1500) == pytest.approx(-(away_new - 1500))


def test_update_ratings_bigger_margin_moves_rating_further():
    small_margin_home, _ = update_ratings(1500, 1500, home_score=20, away_score=18, home_advantage=0)
    big_margin_home, _ = update_ratings(1500, 1500, home_score=40, away_score=0, home_advantage=0)
    assert (big_margin_home - 1500) > (small_margin_home - 1500)


def test_update_ratings_margin_multiplier_has_diminishing_returns():
    # Going from a 2-point win to a 20-point win should move the rating more
    # than going from a 20-point win to a 38-point win (same +18 margin delta).
    small_gap_home, _ = update_ratings(1500, 1500, home_score=20, away_score=18, home_advantage=0)
    mid_gap_home, _ = update_ratings(1500, 1500, home_score=38, away_score=18, home_advantage=0)
    large_gap_home, _ = update_ratings(1500, 1500, home_score=56, away_score=18, home_advantage=0)
    first_jump = mid_gap_home - small_gap_home
    second_jump = large_gap_home - mid_gap_home
    assert first_jump > second_jump > 0


def test_update_ratings_home_advantage_reduces_home_gain_on_expected_win():
    # A higher home_advantage means the home win was "more expected", so the
    # home team's rating gain for the same scoreline should shrink.
    no_advantage_home, _ = update_ratings(1500, 1500, home_score=24, away_score=10, home_advantage=0)
    with_advantage_home, _ = update_ratings(1500, 1500, home_score=24, away_score=10, home_advantage=100)
    assert with_advantage_home < no_advantage_home


def test_update_ratings_home_advantage_not_persisted_onto_rating():
    # home_advantage shapes the *update*, but the returned ratings are the
    # teams' own ratings — home_advantage must not be baked into home_new.
    home_new, _ = update_ratings(1500, 1500, home_score=24, away_score=10, home_advantage=100)
    assert home_new < 1500 + 100  # sanity: the whole advantage wasn't added on top


def test_update_ratings_deterministic():
    result_a = update_ratings(1620, 1480, home_score=18, away_score=22, home_advantage=50)
    result_b = update_ratings(1620, 1480, home_score=18, away_score=22, home_advantage=50)
    assert result_a == result_b


def test_defaults_are_reasonable():
    assert DEFAULT_K_FACTOR > 0
    assert DEFAULT_HOME_ADVANTAGE > 0
