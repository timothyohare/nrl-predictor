"""GET /nfl/accuracy?season=YYYY (spec Phase 4).

Grades the newest OK prediction per game (live and backfilled alike; the count of
backfilled ones is reported) against the results in `nfl_games`, with the Phase 2
metric definitions (common/nfl/backtest.py): accuracy excludes ties; Brier is
(p_home - outcome)^2 with a tie as 0.5; margin MAE is |signed home margin - result|.
Baselines: always-home, and the betting market (comparison only).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from common.dynamo import scan_all
from common.nfl.backtest import (
    CONFIDENCE_LEVELS,
    Scored,
    home_scored,
    market_scored,
    summarise,
)
from common.nfl.games import Game, Market
from nfl.api.http import SEASONS, error, parse_int, respond
from nfl.api.store import (
    game_from_item,
    games_table,
    latest_ok_predictions,
    market_from_item,
    season_games,
)

logger = logging.getLogger(__name__)

# Home baseline, from the model's own fit window (nflverse seasons 1999-2015,
# games.csv sha256 923f23df..., see common/nfl/model.py): home win rate over
# decided games and mean home-minus-away result — common/nfl/backtest.py::home_baseline.
HOME_BASELINE_P_HOME = 0.5727
HOME_BASELINE_MARGIN = 2.60


@dataclass(frozen=True)
class _Graded:
    """One played game with its newest OK prediction, parsed up front."""

    game: Game
    scored: Scored
    confidence: str
    backfilled: bool
    market: Market | None


def _grade(pred: dict, item: dict) -> _Graded | None:
    """None for an unplayed game. Raises on a malformed row."""
    game = game_from_item(item)
    if game.result is None:
        return None
    pick_home = pred["predicted_winner"] == game.home
    margin = int(pred["predicted_margin"])
    scored = Scored(game.result, float(pred["home_win_probability"]), pick_home,
                    margin if pick_home else -margin)
    return _Graded(game, scored, pred["confidence"], bool(pred.get("backfilled")),
                   market_from_item(item))


def _graded(latest: dict[str, dict], games: dict[str, dict]) -> list[_Graded]:
    """Every game still in nfl_games that has been played, skipping (and logging)
    a malformed row rather than failing the whole endpoint (review N1)."""
    graded = []
    for mid, pred in latest.items():
        if mid not in games:
            continue
        try:
            row = _grade(pred, games[mid])
        except Exception:
            logger.warning("Skipping malformed NFL prediction/game row %s", mid, exc_info=True)
            continue
        if row is not None:
            graded.append(row)
    return graded


def _latest_season() -> int | None:
    items = scan_all(games_table(), ProjectionExpression="#s",
                     ExpressionAttributeNames={"#s": "season"})
    return max((int(i["season"]) for i in items), default=None)


def lambda_handler(event: dict, context) -> dict:
    query = event.get("queryStringParameters") or {}
    if "season" in query:
        season = parse_int(query["season"], SEASONS)
        if season is None:
            return error(400, f"season must be an integer {SEASONS[0]}-{SEASONS[1]}")
    else:
        season = _latest_season()
        if season is None:
            return error(404, "No NFL games yet")

    games = season_games(season)
    if not games:
        return error(404, f"No NFL games for season {season}")

    graded = _graded(latest_ok_predictions(season), games)

    model = summarise([row.scored for row in graded])
    by_confidence = {}
    for level in CONFIDENCE_LEVELS:
        level_summary = summarise([row.scored for row in graded if row.confidence == level])
        by_confidence[level] = {"n": level_summary["n"], "accuracy": level_summary["accuracy"]}

    results = [row.scored.result for row in graded]
    markets = {row.game.match_id: row.market for row in graded if row.market}
    return respond(200, {
        "season": season,
        **model,
        "n_backfilled": sum(row.backfilled for row in graded),
        "by_confidence": by_confidence,
        "baselines": {
            "home": {
                "p_home": HOME_BASELINE_P_HOME,
                "margin": HOME_BASELINE_MARGIN,
                **summarise(home_scored(results, HOME_BASELINE_P_HOME, HOME_BASELINE_MARGIN)),
            },
            "market": summarise(market_scored([row.game for row in graded], markets)),
        },
    })
