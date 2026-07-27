from unittest.mock import patch

from v1.agent.tools.fantasy_stats import _squad_id_for, get_fantasy_stats

_SQUADS = [
    {"id": 500011, "name": "Broncos", "full_name": "Brisbane Broncos", "short_name": "BRI"},
    {"id": 500010, "name": "Bulldogs", "full_name": "Canterbury Bulldogs", "short_name": "CBY"},
    {"id": 500002, "name": "Sea Eagles", "full_name": "Manly-Warringah Sea Eagles", "short_name": "MAN"},
    {"id": 500023, "name": "Tigers", "full_name": "Wests Tigers", "short_name": "WST"},
    # Real fantasy.nrl.com data (confirmed live 2026-07-27): "St." with a
    # period, unlike our registry's "St George Illawarra Dragons".
    {"id": 500022, "name": "Dragons", "full_name": "St. George Illawarra Dragons", "short_name": "SGI"},
]

_PLAYERS = [
    {
        "id": 1, "first_name": "Payne", "last_name": "Haas",
        "squad_id": 500011, "cost": 779000, "status": "injured", "locked": 0,
        "stats": {"prices": {"9": 900000, "10": 840000, "11": 779000},
                  "avg_points": 55, "last_3_avg": 44, "tog": 61},
    },
    {
        "id": 2, "first_name": "Adam", "last_name": "Reynolds",
        "squad_id": 500011, "cost": 920000, "status": "playing", "locked": 0,
        "stats": {"prices": {"9": 920000, "10": 920000, "11": 920000},
                  "avg_points": 70, "last_3_avg": 72, "tog": 80},
    },
    {
        "id": 3, "first_name": "Xavier", "last_name": "Coates",
        "squad_id": 500011, "cost": 600000, "status": "playing", "locked": 0,
        "stats": {"prices": {"9": 700000, "10": 650000, "11": 600000},
                  "avg_points": 40, "last_3_avg": 38, "tog": 75},
    },
    {
        "id": 4, "first_name": "Tom", "last_name": "Doyle",
        "squad_id": 500010, "cost": 500000, "status": "playing", "locked": 0,
        "stats": {"prices": {"11": 500000}, "avg_points": 30, "last_3_avg": 30, "tog": 70},
    },
    {
        "id": 5, "first_name": "Tom", "last_name": "Trbojevic",
        "squad_id": 500002, "cost": 850000, "status": "injured", "locked": 0,
        "stats": {"prices": {"11": 850000}, "avg_points": 65, "last_3_avg": 60, "tog": 78},
    },
]


def _patched(fn):
    return patch("v1.agent.tools.fantasy_stats._fetch_squads", return_value=_SQUADS)(
           patch("v1.agent.tools.fantasy_stats._fetch_players", return_value=_PLAYERS)(fn))


@_patched
def test_returns_injured_in_unavailable(*_):
    result = get_fantasy_stats("Broncos")
    names = [p["name"] for p in result["unavailable"]]
    assert "Payne Haas" in names


@_patched
def test_playing_players_not_in_unavailable(*_):
    result = get_fantasy_stats("Broncos")
    names = [p["name"] for p in result["unavailable"]]
    assert "Adam Reynolds" not in names


@_patched
def test_price_drop_alert_for_significant_drop(*_):
    # Xavier Coates: 700k → 600k = -14.3% drop
    result = get_fantasy_stats("Broncos")
    alert_names = [p["name"] for p in result["price_alerts"]]
    assert "Xavier Coates" in alert_names


@_patched
def test_no_price_alert_for_stable_price(*_):
    # Reynolds: flat at 920k
    result = get_fantasy_stats("Broncos")
    alert_names = [p["name"] for p in result["price_alerts"]]
    assert "Adam Reynolds" not in alert_names


@_patched
def test_only_returns_players_for_requested_team(*_):
    result = get_fantasy_stats("Broncos")
    all_names = (
        [p["name"] for p in result["unavailable"]]
        + [p["name"] for p in result["price_alerts"]]
    )
    assert "Tom Doyle" not in all_names


@_patched
def test_unknown_team_returns_empty(*_):
    result = get_fantasy_stats("Unknown FC")
    assert result["unavailable"] == []
    assert result["price_alerts"] == []


@_patched
def test_matches_slugged_team_argument(*_):
    """Regression test for the confirmed production bug: get_fantasy_stats
    never matched a slugged input ("sea-eagles") against the fantasy API's
    own space-separated naming ("Sea Eagles") — a plain .lower() comparison
    of the raw arg against squad name/full_name can never bridge the two
    formats."""
    result = get_fantasy_stats("sea-eagles")
    names = [p["name"] for p in result["unavailable"]]
    assert "Tom Trbojevic" in names


def test_squad_id_for_matches_nickname_and_slug_input():
    assert _squad_id_for("Sea Eagles", _SQUADS) == 500002
    assert _squad_id_for("sea-eagles", _SQUADS) == 500002


def test_squad_id_for_matches_when_api_name_is_shortened():
    # Fantasy API's squad "name" is "Tigers", not "Wests Tigers" — our
    # registry's nickname/full_name are both "Wests Tigers", so the match
    # has to land on full_name.
    assert _squad_id_for("wests-tigers", _SQUADS) == 500023
    assert _squad_id_for("Wests Tigers", _SQUADS) == 500023


def test_squad_id_for_tolerates_punctuation_mismatch():
    # Confirmed live against fantasy.nrl.com (2026-07-27): its full_name has
    # a period ("St. George..."), our registry's doesn't ("St George...") —
    # a plain .lower() equality check would miss this.
    assert _squad_id_for("dragons", _SQUADS) == 500022
    assert _squad_id_for("St George Illawarra Dragons", _SQUADS) == 500022
