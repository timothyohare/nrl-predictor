"""GET /nfl/predictions/{season}/{week} (spec Phase 4).

The newest OK prediction per game for the week, joined by matchId (season- and
week-qualified, so the join is round-aware) to `nfl_games` for the result and the
betting-market comparison. The join only ever runs this way round: the market is
attached to a finished prediction for display and never feeds the model.

Only games still present in `nfl_games` for that season+week are served — a
rescheduled game leaves an orphan prediction under its old matchId, and the
fixture's current venue (`neutral`) and kickoff come from the game, not the
frozen prediction row.
"""
from __future__ import annotations

from common.nfl.backtest import devig_home_probability
from common.nfl.match_id import stage_label
from common.nfl.teams import display_name
from nfl.api.http import SEASONS, WEEKS, error, parse_int, respond
from nfl.api.store import latest_ok_predictions, season_games

# |signed predicted home margin - spread_line| above this flags an outlier.
OUTLIER_MARGIN_GAP = 3

_PASS_THROUGH = (
    "predicted_winner", "predicted_margin", "margin_low", "margin_high",
    "home_win_probability", "confidence", "key_factors", "reasoning", "model_used",
    "generation", "generatedAt",
)


def _result(game: dict) -> dict | None:
    if game.get("home_score") is None or game.get("away_score") is None:
        return None
    home, away = int(game["home_score"]), int(game["away_score"])
    winner = game["home_team"] if home > away else game["away_team"] if away > home else None
    return {
        "home_score": home,
        "away_score": away,
        "winner": winner,
        "winner_name": display_name(winner) if winner else None,
        "margin": abs(home - away),
    }


def _market(game: dict) -> dict | None:
    market = game.get("market") or {}
    if not market:
        return None
    spread = market.get("spread_line")
    spread = None if spread is None else float(spread)
    favourite = None
    if spread:
        favourite = game["home_team"] if spread > 0 else game["away_team"]
    home_ml, away_ml = market.get("home_moneyline"), market.get("away_moneyline")
    implied = None
    if home_ml is not None and away_ml is not None:
        implied = devig_home_probability(int(home_ml), int(away_ml))
    return {"spread_favourite": favourite, "spread_line": spread, "implied_home_prob": implied}


def _is_outlier(pred: dict, home: str, market: dict) -> bool | None:
    """None when there is no spread to compare against (field then omitted)."""
    spread = market["spread_line"]
    if spread is None:
        return None
    winner = pred["predicted_winner"]
    margin = int(pred["predicted_margin"])
    signed = margin if winner == home else -margin
    favourite = market["spread_favourite"]
    return (favourite is not None and favourite != winner) or abs(signed - spread) > OUTLIER_MARGIN_GAP


def present(pred: dict, game: dict) -> dict:
    home, away = game["home_team"], game["away_team"]
    week = int(game["week"])
    out = {
        "matchId": pred["matchId"],
        "season": int(game["season"]),
        "week": week,
        "stage": game["stage"],
        "label": stage_label(game["stage"], week),
        "home_team": home,
        "home_team_name": display_name(home),
        "away_team": away,
        "away_team_name": display_name(away),
        "neutral": bool(game.get("neutral", False)),
        "kickoff_utc": game.get("kickoff_utc"),
        **{k: pred.get(k) for k in _PASS_THROUGH},
        "predicted_winner_name": display_name(pred["predicted_winner"]),
        "backfilled": bool(pred.get("backfilled", False)),
    }
    result = _result(game)
    if result:
        out["result"] = result
    market = _market(game)
    if market:
        out["market"] = market
        outlier = _is_outlier(pred, home, market)
        if outlier is not None:
            out["is_outlier"] = outlier
    return out


def lambda_handler(event: dict, context) -> dict:
    params = event.get("pathParameters") or {}
    season = parse_int(params.get("season"), SEASONS)
    week = parse_int(params.get("week"), WEEKS)
    if season is None or week is None:
        return error(400, f"season must be an integer {SEASONS[0]}-{SEASONS[1]} "
                          f"and week an integer {WEEKS[0]}-{WEEKS[1]}")

    games = season_games(season, week)
    latest = {mid: row for mid, row in latest_ok_predictions(season, week).items() if mid in games}
    if not latest:
        return error(404, f"No NFL predictions for {season} week {week}")

    predictions = sorted(
        (present(row, games[mid]) for mid, row in latest.items()),
        key=lambda p: (p["kickoff_utc"] is None, p["kickoff_utc"] or "", p["matchId"]),
    )
    return respond(200, predictions, cache="public, max-age=300")
