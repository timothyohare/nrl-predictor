"""GET /nfl/accuracy?season=YYYY (spec Phase 4).

Grades the newest OK prediction per game (live and backfilled alike; the count of
backfilled ones is reported) against the results in `nfl_games`, with the Phase 2
metric definitions (common/nfl/backtest.py): accuracy excludes ties; Brier is
(p_home - outcome)^2 with a tie as 0.5; margin MAE is |signed home margin - result|.
Baselines: always-home, and the betting market (comparison only).
"""
from __future__ import annotations

from common.dynamo import scan_all
from common.nfl.backtest import (
    CONFIDENCE_LEVELS,
    Scored,
    home_scored,
    market_scored,
    summarise,
)
from common.nfl.games import Game
from nfl.api.http import SEASONS, error, parse_int, respond
from nfl.api.store import (
    game_from_item,
    games_table,
    latest_ok_predictions,
    market_from_item,
    season_games,
)

# Home baseline, from the model's own fit window (nflverse seasons 1999-2015,
# games.csv sha256 923f23df..., see common/nfl/model.py): home win rate over
# decided games and mean home-minus-away result — common/nfl/backtest.py::home_baseline.
HOME_BASELINE_P_HOME = 0.5727
HOME_BASELINE_MARGIN = 2.60


def _result(game: Game) -> int:
    assert game.result is not None  # only played games are graded
    return game.result


def _scored(pred: dict, game: Game) -> Scored:
    pick_home = pred["predicted_winner"] == game.home
    margin = int(pred["predicted_margin"])
    return Scored(_result(game), float(pred["home_win_probability"]), pick_home,
                  margin if pick_home else -margin)


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

    # (prediction, game) for every graded game: still in nfl_games and played.
    graded: list[tuple[dict, Game]] = []
    for mid, pred in latest_ok_predictions(season).items():
        if mid in games:
            game = game_from_item(games[mid])
            if game.played:
                graded.append((pred, game))

    model = summarise([_scored(p, g) for p, g in graded])
    by_confidence = {}
    for level in CONFIDENCE_LEVELS:
        level_summary = summarise([_scored(p, g) for p, g in graded if p["confidence"] == level])
        by_confidence[level] = {"n": level_summary["n"], "accuracy": level_summary["accuracy"]}

    results = [_result(g) for _, g in graded]
    markets = {g.match_id: m for _, g in graded if (m := market_from_item(games[g.match_id]))}
    return respond(200, {
        "season": season,
        **model,
        "n_backfilled": sum(bool(p.get("backfilled")) for p, _ in graded),
        "by_confidence": by_confidence,
        "baselines": {
            "home": {
                "p_home": HOME_BASELINE_P_HOME,
                "margin": HOME_BASELINE_MARGIN,
                **summarise(home_scored(results, HOME_BASELINE_P_HOME, HOME_BASELINE_MARGIN)),
            },
            "market": summarise(market_scored([g for _, g in graded], markets)),
        },
    })
