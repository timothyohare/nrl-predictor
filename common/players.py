"""Best-effort matching between `injuries`-table player mentions and a team
sheet's spine players — the injury signal for `stats-elo-v1`
(docs/plans/11-team-sheet-injury-weather-signals.md, Phase 3).

Matching is name-slug equality only — deliberately conservative. A player
whose article-extracted name doesn't slug-match the team sheet exactly
resolves to "no mention", never a guessed match; a wrong-player adjustment
is worse than a missed one.
"""
from __future__ import annotations

import re

from common.team_sheet import HIGH_IMPACT_JERSEYS

_OUT_STATUSES = {"out", "doubtful"}

# Provisional — only ~59 historical mentions exist across the whole `injuries`
# table (2026-08-27), nowhere near enough to fit a real coefficient. Refit in
# Phase 5 of docs/plans/11-team-sheet-injury-weather-signals.md.
PROVISIONAL_INJURY_PENALTY = -20.0  # Elo points


def player_slug(name: str) -> str:
    """Same normalization as scrapers/articles/lambda_handler.py::_player_slug
    so a team-sheet full name and an injuries-table pk are directly comparable.
    """
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def spine_player_slugs(sheet: dict, side: str) -> dict[int, str]:
    """jersey_number -> player_slug for the spine positions (1/6/7/9) named
    in `sheet[side]` ("homePlayers"/"awayPlayers")."""
    return {
        p["jersey_number"]: player_slug(f"{p['first_name']} {p['last_name']}")
        for p in sheet.get(side, [])
        if p["jersey_number"] in HIGH_IMPACT_JERSEYS
    }


def latest_status(injuries_table, team: str, player_slug_value: str, before: str | None = None) -> str | None:
    """Most recent status ("out"/"doubtful"/"available"/"returning") mentioned
    for this player, optionally restricted to mentions scraped at or before
    `before` (an ISO timestamp), or None if no (qualifying) mention exists.
    """
    key_condition = "pk = :pk"
    values = {":pk": f"injury#{team}#{player_slug_value}"}
    if before:
        key_condition += " AND sk <= :before"
        values[":before"] = before
    resp = injuries_table.query(
        KeyConditionExpression=key_condition,
        ExpressionAttributeValues=values,
        ScanIndexForward=False,
        Limit=1,
    )
    items = resp.get("Items", [])
    return items[0]["status"] if items else None


def has_spine_player_ruled_out(
    sheet: dict, side: str, team: str, injuries_table, before: str | None = None
) -> bool:
    """True if any currently-named spine player for `side` has a most-recent
    injuries-table mention of "out"/"doubtful". A later "available"/
    "returning" mention (handled by `latest_status` always returning the
    single most recent row) cancels an earlier "out"/"doubtful". Fails open
    (False) when `injuries_table` is None.
    """
    if injuries_table is None:
        return False
    for slug in spine_player_slugs(sheet, side).values():
        if latest_status(injuries_table, team, slug, before) in _OUT_STATUSES:
            return True
    return False


def injury_adjustment(spine_player_ruled_out: bool) -> float:
    """Effective-rating adjustment for one side. 0.0 (inert) when False —
    callers should treat "no data"/False identically, never as an error.
    """
    return PROVISIONAL_INJURY_PENALTY if spine_player_ruled_out else 0.0
