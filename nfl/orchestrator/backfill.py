"""Labelled walk-forward backfill (user decision Q2, spec Phase 3).

The live pipeline only ever predicts games still to kick off, so weeks of the
current season played before the first live run would have no predictions. This
fills them with walk-forward predictions labelled ``backfilled: true`` (the site
shows a "backtest" badge for them, Phase 5):

- every game in week N is predicted from ratings replayed strictly before week N
  (no look-ahead, same rule as the live run and the Phase 2 backtest);
- only weeks before the first live week are touched — the earliest week with a
  live (non-backfilled) OK prediction, else the current target week — and never
  the target week itself or later;
- a game that already has any OK prediction is skipped, so a backfilled row can
  never shadow a live one and reruns are idempotent.
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from boto3.dynamodb.conditions import Attr

from common.dynamo import scan_all
from common.nfl.games import Game
from common.nfl.model import NFL
from common.stats_model.ratings import replay_ratings
from nfl.orchestrator.lambda_handler import has_ok, prediction_rows, store_prediction
from nfl.orchestrator.target_week import select_target


def _first_live_week(table, season: int) -> int | None:
    rows = scan_all(
        table,
        FilterExpression=Attr("season").eq(season)
        & Attr("status").eq("OK")
        & Attr("backfilled").ne(True),
    )
    return min((int(r["week"]) for r in rows), default=None)


def backfill(
    games: Iterable[Game],
    predictions_table,
    now: datetime,
    *,
    through_week: int | None = None,
    dry_run: bool = False,
) -> list[str]:
    """Backfill the current season up to `through_week` (default: the week before
    the first live week). Returns the matchIds written (or, with `dry_run`, that
    would be written)."""
    games = list(games)
    target = select_target(games, now)
    if target.season is None:
        return []
    season = target.season
    current = [g for g in games if g.season == season]

    if through_week is None:
        first_live = _first_live_week(predictions_table, season) or target.week
        through_week = first_live - 1 if first_live is not None else max(g.week for g in current)
    if target.week is not None:
        through_week = min(through_week, target.week - 1)

    written: list[str] = []
    for week in sorted({g.week for g in current if g.week <= through_week}):
        ratings = replay_ratings(games, NFL, before=(season, week))
        for game in sorted((g for g in current if g.week == week), key=lambda g: g.match_id):
            rows = prediction_rows(predictions_table, game.match_id)
            if has_ok(rows):
                continue
            if dry_run or store_prediction(predictions_table, game, ratings,
                                           generation=len(rows) + 1, backfilled=True, now=now):
                written.append(game.match_id)
    return written
