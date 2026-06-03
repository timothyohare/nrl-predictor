import pytest
from agent.tools.momentum import calculate_momentum


def _make_results(form_string: str) -> list[dict]:
    """Create mock results from a form string like 'WWLWLL' (most recent first)."""
    results = []
    for i, char in enumerate(form_string):
        is_win = char == "W"
        results.append({
            "scoredAt": f"2026-05-{20-i:02d}T10:00:00Z",
            "homeTeam": "Panthers",
            "awayTeam": f"Team{i}",
            "homeScore": 24 if is_win else 14,
            "awayScore": 14 if is_win else 24,
            "winner": "Panthers" if is_win else f"Team{i}",
            "margin": 10,
        })
    return results


def test_all_wins():
    results = _make_results("WWWWWW")
    m = calculate_momentum(results, team="Panthers")
    assert m["weighted_win_rate"] == 1.0
    assert m["momentum_direction"] == "stable"
    assert m["streak"] == "W6"


def test_all_losses():
    results = _make_results("LLLLLL")
    m = calculate_momentum(results, team="Panthers")
    assert m["weighted_win_rate"] == 0.0
    assert m["momentum_direction"] == "stable"
    assert m["streak"] == "L6"


def test_rising_momentum():
    # Most recent are wins, older are losses
    results = _make_results("WWWLLL")
    m = calculate_momentum(results, team="Panthers")
    assert m["momentum_direction"] == "rising"
    assert m["weighted_win_rate"] > 0.5  # Weighted towards recent wins
    assert m["streak"] == "W3"


def test_falling_momentum():
    # Most recent are losses, older are wins
    results = _make_results("LLLWWW")
    m = calculate_momentum(results, team="Panthers")
    assert m["momentum_direction"] == "falling"
    assert m["weighted_win_rate"] < 0.5  # Weighted towards recent losses
    assert m["streak"] == "L3"


def test_stable_alternating():
    results = _make_results("WLWLWL")
    m = calculate_momentum(results, team="Panthers")
    assert m["momentum_direction"] == "stable"


def test_momentum_score_range():
    for form in ["WWWWWW", "LLLLLL", "WWWLLL", "LLLWWW", "WLWLWL"]:
        results = _make_results(form)
        m = calculate_momentum(results, team="Panthers")
        assert -1.0 <= m["momentum_score"] <= 1.0


def test_empty_results():
    m = calculate_momentum([], team="Panthers")
    assert m["weighted_win_rate"] == 0.0
    assert m["momentum_direction"] == "stable"
    assert m["streak"] == ""
    assert m["momentum_score"] == 0.0


def test_single_result():
    results = _make_results("W")
    m = calculate_momentum(results, team="Panthers")
    assert m["weighted_win_rate"] == 1.0
    assert m["streak"] == "W1"


def test_form_string():
    results = _make_results("WWLWLL")
    m = calculate_momentum(results, team="Panthers")
    assert m["form_string"] == "W W L W L L"


def test_weighted_points():
    results = _make_results("WWWLLL")
    m = calculate_momentum(results, team="Panthers")
    # Most recent 3 wins have scores 24-14, weighted heavily
    # Older 3 losses have scores 14-24, weighted less
    assert m["weighted_points_for"] > m["weighted_points_against"]


def test_decay_factor_effect():
    results = _make_results("WWWLLL")
    # Higher decay = more weight on recent games
    m_high = calculate_momentum(results, team="Panthers", decay_factor=0.9)
    m_low = calculate_momentum(results, team="Panthers", decay_factor=0.5)
    # With rising form (recent wins), higher decay should give higher win rate
    # because older losses are weighted nearly equally with 0.9
    # Actually opposite: lower decay means recent games matter MORE relative to old
    assert m_low["weighted_win_rate"] > m_high["weighted_win_rate"]
