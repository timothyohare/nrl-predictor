"""Tests for the Monte Carlo match simulator (common/stats_model/simulate.py). See docs/plans/10."""
import random

import pytest

from common.stats_model.elo import DEFAULT_HOME_ADVANTAGE, expected_score
from common.stats_model.simulate import simulate_match


def test_win_probability_monotonic_in_rating_diff():
    rng = random.Random(1)
    low_diff = simulate_match(1500, 1500, home_advantage=0, n=5000, rng=rng)
    high_diff = simulate_match(1650, 1500, home_advantage=0, n=5000, rng=rng)
    assert high_diff.home_win_probability > low_diff.home_win_probability


def test_home_advantage_raises_home_win_probability():
    rng = random.Random(1)
    no_advantage = simulate_match(1500, 1500, home_advantage=0, n=5000, rng=rng)
    with_advantage = simulate_match(1500, 1500, home_advantage=DEFAULT_HOME_ADVANTAGE, n=5000, rng=rng)
    assert with_advantage.home_win_probability > no_advantage.home_win_probability


def test_monte_carlo_converges_to_closed_form_probability():
    rng = random.Random(42)
    result = simulate_match(1620, 1480, home_advantage=0, n=20000, rng=rng)
    closed_form = expected_score(1620, 1480)
    assert result.home_win_probability == pytest.approx(closed_form, abs=0.02)


def test_expected_margin_tracks_rating_diff_direction():
    rng = random.Random(7)
    small_favourite = simulate_match(1520, 1500, home_advantage=0, n=5000, rng=rng)
    big_favourite = simulate_match(1700, 1500, home_advantage=0, n=5000, rng=rng)
    assert big_favourite.expected_margin > small_favourite.expected_margin > 0


def test_underdog_home_team_has_negative_expected_margin():
    rng = random.Random(3)
    result = simulate_match(1400, 1700, home_advantage=0, n=5000, rng=rng)
    assert result.expected_margin < 0
    assert result.home_win_probability < 0.5


def test_deterministic_given_seeded_rng():
    result_a = simulate_match(1550, 1500, home_advantage=50, n=2000, rng=random.Random(99))
    result_b = simulate_match(1550, 1500, home_advantage=50, n=2000, rng=random.Random(99))
    assert result_a == result_b


def test_n_matches_requested():
    result = simulate_match(1500, 1500, home_advantage=0, n=1234, rng=random.Random(0))
    assert result.n == 1234


def test_magnitude_symmetric_in_elo_diff_sign():
    # Two mirror-image matchups (home favoured by X vs home underdog by X)
    # should produce the same |expected_margin| — magnitude is driven by the
    # absolute rating gap, not by which side happens to be favoured. A margin
    # model fit on *signed* margin (rather than |margin| ~ |elo_diff|) can
    # leak a spurious sign-dependent asymmetry from its intercept; this
    # guards against that regression (see docs/plans/10, margin calibration).
    favoured = simulate_match(1650, 1500, home_advantage=0, n=8000, rng=random.Random(11))
    underdog = simulate_match(1500, 1650, home_advantage=0, n=8000, rng=random.Random(11))
    assert abs(favoured.expected_margin) == pytest.approx(abs(underdog.expected_margin), rel=0.05)
