"""Reads shared by the NFL API handlers: table handles from env, nfl_games items
back into `Game`/`Market`, and the latest OK prediction per game."""
from __future__ import annotations

import os
from collections.abc import Iterable
from datetime import datetime

import boto3
from boto3.dynamodb.conditions import Attr

from common.dynamo import scan_all
from common.nfl.games import Game, Market


def games_table():
    return boto3.resource("dynamodb").Table(os.environ["NFL_GAMES_TABLE"])


def predictions_table():
    return boto3.resource("dynamodb").Table(os.environ["NFL_PREDICTIONS_TABLE"])


def _int_or_none(value) -> int | None:
    return None if value is None else int(value)


def game_from_item(item: dict) -> Game:
    kickoff = item.get("kickoff_utc")
    return Game(
        game_id=item.get("game_id", ""),
        match_id=item["matchId"],
        season=int(item["season"]),
        week=int(item["week"]),
        stage=item["stage"],
        home=item["home_team"],
        away=item["away_team"],
        home_score=_int_or_none(item.get("home_score")),
        away_score=_int_or_none(item.get("away_score")),
        neutral=bool(item.get("neutral", False)),
        kickoff_utc=datetime.fromisoformat(kickoff) if kickoff else None,
    )


def market_from_item(item: dict) -> Market | None:
    market = item.get("market") or {}
    if not market:
        return None
    spread = market.get("spread_line")
    return Market(
        match_id=item["matchId"],
        spread_line=None if spread is None else float(spread),
        home_moneyline=_int_or_none(market.get("home_moneyline")),
        away_moneyline=_int_or_none(market.get("away_moneyline")),
    )


def season_games(season: int, week: int | None = None) -> dict[str, dict]:
    """nfl_games items for `season` (and `week`), keyed by matchId."""
    condition = Attr("season").eq(season)
    if week is not None:
        condition = condition & Attr("week").eq(week)
    return {i["matchId"]: i for i in scan_all(games_table(), FilterExpression=condition)}


def latest_ok_predictions(season: int, week: int | None = None) -> dict[str, dict]:
    """The newest OK nfl_predictions row per matchId for `season` (and `week`)."""
    condition = Attr("season").eq(season) & Attr("status").eq("OK")
    if week is not None:
        condition = condition & Attr("week").eq(week)
    return latest_by_match(scan_all(predictions_table(), FilterExpression=condition))


def latest_by_match(rows: Iterable[dict]) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for row in rows:
        mid = row["matchId"]
        if mid not in latest or row["generatedAt"] > latest[mid]["generatedAt"]:
            latest[mid] = row
    return latest
