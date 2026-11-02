"""NFL match identity (common/nfl/match_id.py) — spec criteria 2.2 and 2.3."""
from __future__ import annotations

import pytest

from common import match_id as nrl_match_id
from common.nfl.match_id import match_id, parse, stage_label


def test_match_id_is_season_and_week_qualified_slugs():
    assert match_id(2026, 8, "KC", "LV") == "nfl-2026-week-8-chiefs-v-raiders"


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ((2026, 8, "KC", "LV"), (2026, 8, "chiefs", "raiders")),
        ((2021, 19, "SF", "DAL"), (2021, 19, "49ers", "cowboys")),
        ((2025, 3, "49ers", "rams"), (2025, 3, "49ers", "rams")),
    ],
)
def test_parse_round_trips(args, expected):
    assert parse(match_id(*args)) == expected


@pytest.mark.parametrize(
    "bad", ["round-8-chiefs-v-raiders", "nfl-2026-week-x-chiefs-v-raiders", "nfl-2026-week-8-chiefs", ""]
)
def test_parse_rejects_non_nfl_ids(bad):
    with pytest.raises(ValueError):
        parse(bad)


def test_nfl_ids_are_never_nrl_canonical():
    nfl_id = match_id(2026, 8, "KC", "LV")
    assert nrl_match_id.is_canonical(nfl_id) is False
    assert nrl_match_id.round_of(nfl_id) is None


@pytest.mark.parametrize(
    ("game_type", "week", "label"),
    [
        ("WC", 18, "Wild Card"),
        ("WC", 19, "Wild Card"),
        ("REG", 18, "Week 18"),
        ("REG", 8, "Week 8"),
        ("DIV", 20, "Divisional"),
        ("CON", 21, "Conference Championship"),
        ("SB", 21, "Super Bowl"),
        ("SB", 22, "Super Bowl"),
    ],
)
def test_stage_label_comes_from_game_type_not_week(game_type, week, label):
    assert stage_label(game_type, week) == label


def test_stage_label_rejects_unknown_game_type():
    with pytest.raises(ValueError):
        stage_label("PRE", 1)
