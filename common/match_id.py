"""Canonical match identity — the single source of truth for the matchId key.

A matchId is the round-qualified slug ``round-<N>-<home>-v-<away>`` where the team
slugs come from the official match-centre URL order (the draw decides which side is
home). Every writer keys on this; every cross-table join is round-aware (by matchId or
roundNumber), never a round-blind team-pair. See docs/matchid-identity-plan.md.
"""
from __future__ import annotations

import re

from common.teams import to_slug

_ROUND_PREFIX = re.compile(r"^round-\d+-")
_FINALS_WEEK_SEGMENT = re.compile(r"^finals-week-(\d+)$")
_ROUND_TITLE = re.compile(r"^Round (\d+)$")
_FINALS_WEEK_TITLE = re.compile(r"^Finals Week (\d+)$")

REGULAR_SEASON_ROUNDS = 27
"""Length of the NRL regular season. Finals follow as rounds
REGULAR_SEASON_ROUNDS+1..+3 (Finals Week 1-3) then REGULAR_SEASON_ROUNDS+4
(Grand Final) — see round_number_from_title()."""


def match_id_from_url(match_centre_url: str) -> str:
    """Canonical matchId from a match-centre URL.

    ``/draw/nrl-premiership/2026/round-11/panthers-v-broncos/`` -> ``round-11-panthers-v-broncos``.
    The last two path segments (``round-11`` + ``panthers-v-broncos``) are joined; the team
    portion is left in the URL's official home-v-away order.

    Finals URLs use non-numeric segments (``finals-week-1``, ``grand-final``) instead of
    ``round-N`` — translated onto the same round-qualified numbering as
    round_number_from_title() so every matchId stays round-<N>-prefixed, finals included.
    """
    parts = match_centre_url.rstrip("/").rsplit("/", 2)  # pragma: no mutate — maxsplit/charset are inert: output reads parts[-2:] either way
    if len(parts) < 3:
        return parts[-1]
    round_segment, teams_segment = parts[-2], parts[-1]
    m = _FINALS_WEEK_SEGMENT.match(round_segment)
    if m:
        round_segment = f"round-{REGULAR_SEASON_ROUNDS + int(m.group(1))}"
    elif round_segment == "grand-final":
        round_segment = f"round-{REGULAR_SEASON_ROUNDS + 4}"
    return f"{round_segment}-{teams_segment}"


def round_number_from_title(round_title: str) -> tuple[int, bool]:
    """Parse the NRL API's roundTitle into (round_number, is_finals).

    ``"Round 11"`` -> ``(11, False)``. Finals use ``"Finals Week N"`` ->
    ``(REGULAR_SEASON_ROUNDS + N, True)`` and ``"Grand Final"`` ->
    ``(REGULAR_SEASON_ROUNDS + 4, True)``. Raises ValueError on anything else —
    the previous ``roundTitle.split()[-1]`` approach silently collided Finals
    Week 1 with Round 1 and sent the Grand Final's round_number to None.
    """
    title = (round_title or "").strip()
    if title == "Grand Final":
        return REGULAR_SEASON_ROUNDS + 4, True
    m = _FINALS_WEEK_TITLE.match(title)
    if m:
        return REGULAR_SEASON_ROUNDS + int(m.group(1)), True
    m = _ROUND_TITLE.match(title)
    if m:
        return int(m.group(1)), False
    raise ValueError(f"Unrecognised roundTitle: {round_title!r}")


def match_id(round_no: int, home: str, away: str) -> str:
    """Canonical matchId from structured fields. ``home``/``away`` may be any inbound team
    form; they are slugged but NOT reordered (the caller supplies official home/away)."""
    return f"round-{int(round_no)}-{to_slug(home)}-v-{to_slug(away)}"


def is_canonical(match_id_str: str) -> bool:
    """True if the matchId carries the ``round-<N>-`` prefix (i.e. is round-qualified)."""
    return bool(_ROUND_PREFIX.match(match_id_str)) if match_id_str else False


def round_of(match_id_str: str) -> int | None:
    """Extract the round number from a round-prefixed matchId, or None."""
    m = re.match(r"^round-(\d+)-", match_id_str) if match_id_str else None
    return int(m.group(1)) if m else None
