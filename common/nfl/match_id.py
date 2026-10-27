"""Canonical NFL match identity: ``nfl-<season>-week-<week>-<home>-v-<away>``.

Season- *and* week-qualified (the same two teams meet twice a season, and every
season), and the ``nfl-`` prefix can never satisfy common.match_id's ``round-``
check, so an NFL id can't be mistaken for an NRL one. Playoff stage always comes
from nflverse ``game_type`` — the playoff week number drifts by season (Wild Card
is week 18 in 2020, week 19 from 2021).
"""
from __future__ import annotations

import re

from common.nfl.teams import to_slug

_MATCH_ID = re.compile(r"^nfl-(\d{4})-week-(\d+)-(.+)-v-(.+)$")

_PLAYOFF_LABELS = {
    "WC": "Wild Card",
    "DIV": "Divisional",
    "CON": "Conference Championship",
    "SB": "Super Bowl",
}


def match_id(season: int, week: int, home: str, away: str) -> str:
    return f"nfl-{season}-week-{week}-{to_slug(home)}-v-{to_slug(away)}"


def parse(match_id_str: str) -> tuple[int, int, str, str]:
    """``nfl-2026-week-8-chiefs-v-raiders`` -> ``(2026, 8, "chiefs", "raiders")``."""
    m = _MATCH_ID.match(match_id_str or "")
    if not m:
        raise ValueError(f"not an NFL matchId: {match_id_str!r}")
    return int(m.group(1)), int(m.group(2)), m.group(3), m.group(4)


def stage_label(game_type: str, week: int) -> str:
    """Display label for a game: "Week 8" for the regular season, the playoff
    round name otherwise (never derived from the week number)."""
    if game_type == "REG":
        return f"Week {week}"
    try:
        return _PLAYOFF_LABELS[game_type]
    except KeyError:
        raise ValueError(f"unknown nflverse game_type: {game_type!r}") from None
