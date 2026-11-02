"""GET /nfl/weeks/current (spec Phase 4): the Phase 3 target week over
`nfl_games` (nfl/orchestrator/target_week.py), so the site and the orchestrator
always agree. With no game left to kick off (after the Super Bowl, or week 18
done before the Wild Card rows exist) it is the last week played.

GET /nfl/weeks?season=YYYY (default: latest season): every week of the season
in `nfl_games` with its stage and label, for the site's week selector — the
label always comes from the stage, never from the week number."""
from __future__ import annotations

from datetime import UTC, datetime

from common.dynamo import scan_all
from common.nfl.match_id import stage_label
from nfl.api.http import SEASONS, error, parse_int, respond
from nfl.api.store import game_from_item, games_table
from nfl.orchestrator.target_week import select_target


def _now() -> datetime:
    return datetime.now(UTC)


def lambda_handler(event: dict, context) -> dict:
    games = [game_from_item(i) for i in scan_all(games_table())]
    target = select_target(games, _now())
    if target.season is None:
        return error(404, "No NFL games yet")
    season = target.season
    week = target.week
    if week is None:
        played = [g.week for g in games if g.season == season and g.played]
        if not played:
            return error(404, f"No NFL week to show for season {season}")
        week = max(played)
    stage = next(g.stage for g in games if g.season == season and g.week == week)
    return respond(200, {"season": season, "week": week, "stage": stage,
                         "label": stage_label(stage, week)}, cache="public, max-age=300")


def list_handler(event: dict, context) -> dict:
    query = event.get("queryStringParameters") or {}
    items = scan_all(games_table(), ProjectionExpression="#s, #w, #g",
                     ExpressionAttributeNames={"#s": "season", "#w": "week", "#g": "stage"})
    if "season" in query:
        season = parse_int(query["season"], SEASONS)
        if season is None:
            return error(400, f"season must be an integer {SEASONS[0]}-{SEASONS[1]}")
    else:
        season = max((int(i["season"]) for i in items), default=None)
        if season is None:
            return error(404, "No NFL games yet")
    stages = {int(i["week"]): i["stage"] for i in items if int(i["season"]) == season}
    if not stages:
        return error(404, f"No NFL games for season {season}")
    return respond(200, {"season": season, "weeks": [
        {"week": week, "stage": stage, "label": stage_label(stage, week)}
        for week, stage in sorted(stages.items())
    ]}, cache="public, max-age=300")
