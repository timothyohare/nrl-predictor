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


def test_margin_stdev_multiplier_does_not_affect_win_probability():
    # Widening/narrowing the margin distribution must not leak into the
    # win/loss draw — that's a separate Bernoulli draw on the closed-form
    # expected score. Same seed on both sides means the rng call sequence
    # (rng.random() then rng.gauss() per trial) is bit-identical regardless
    # of the stdev fed into gauss.
    baseline = simulate_match(1600, 1500, home_advantage=55, n=5000, rng=random.Random(7))
    widened = simulate_match(
        1600, 1500, home_advantage=55, n=5000, rng=random.Random(7), margin_stdev_multiplier=5.0
    )
    assert widened.home_win_probability == baseline.home_win_probability


def test_margin_stdev_multiplier_changes_expected_margin():
    baseline = simulate_match(1600, 1500, home_advantage=55, n=5000, rng=random.Random(7))
    widened = simulate_match(
        1600, 1500, home_advantage=55, n=5000, rng=random.Random(7), margin_stdev_multiplier=5.0
    )
    assert widened.expected_margin != baseline.expected_margin


def test_margin_stdev_multiplier_default_matches_unmultiplied_call():
    # Default (1.0) must reproduce today's behavior exactly — no new call
    # site is forced to change until it opts in.
    explicit_default = simulate_match(
        1550, 1500, home_advantage=50, n=2000, rng=random.Random(99), margin_stdev_multiplier=1.0
    )
    no_param = simulate_match(1550, 1500, home_advantage=50, n=2000, rng=random.Random(99))
    assert explicit_default == no_param


def test_margin_stdev_is_positive():
    result = simulate_match(1600, 1500, home_advantage=50, n=8000, rng=random.Random(1))
    assert result.margin_stdev > 0


def test_margin_stdev_widens_with_multiplier():
    baseline = simulate_match(1650, 1500, home_advantage=50, n=8000, rng=random.Random(4))
    widened = simulate_match(
        1650, 1500, home_advantage=50, n=8000, rng=random.Random(4), margin_stdev_multiplier=3.0
    )
    assert widened.margin_stdev > baseline.margin_stdev


def test_margin_stdev_tracks_the_margin_model_residual():
    # Conditioned on the winner, the winning-margin spread is a one-lobe
    # distribution ~= the fitted margin residual stdev (_MARGIN_STDEV = 14.22),
    # roughly independent of how lopsided the matchup is.
    coinflip = simulate_match(1500, 1500, home_advantage=0, n=10000, rng=random.Random(5))
    blowout = simulate_match(1900, 1400, home_advantage=0, n=10000, rng=random.Random(6))
    assert 10 < coinflip.margin_stdev < 19
    assert 10 < blowout.margin_stdev < 19


def test_winning_margin_mean_exceeds_the_regressed_expected_margin():
    # `expected_margin` averages in the upset trials and is pulled toward zero;
    # `winning_margin_mean` conditions on the favourite winning, so it's larger.
    result = simulate_match(1700, 1500, home_advantage=50, n=10000, rng=random.Random(8))
    assert result.winning_margin_mean > abs(result.expected_margin)


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
