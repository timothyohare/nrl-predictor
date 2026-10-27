"""Daily NFL orchestrator (spec Phase 3): ingest nflverse, predict the next week.

One run, triggered daily by EventBridge with an empty payload (season and week
always come from the data):

1. Read the table names from env (``KeyError`` before any network call).
2. Fetch the nflverse ``games.csv`` from ``NFL_GAMES_CSV_URL`` (default: the
   nflverse URL; ``file://`` is allowed for tests and the gate). A fetch or parse
   failure raises with nothing written, so the Lambda ``Errors`` alarm fires.
3. Upsert the current season's rows into ``nfl_games``. Betting lines live under
   a separate ``market`` map — comparison/display only, never model input.
4. Replay ratings from the whole CSV strictly before the target week (see
   target_week.py) and predict each target-week game still to kick off that
   has no OK prediction yet. Reruns are idempotent; one game failing writes a
   ``FAILED`` row and the rest carry on.
5. Emit ``NflPredictor/UnpredictedGames`` — target-week games still to kick off
   with no OK prediction after the run. A once-a-day pulse, alarmed with a 24h
   period + IGNORE missing data (see infra/nfl_stack.py).
"""
from __future__ import annotations

import logging
import os
import random
import urllib.request
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

from common.nfl.games import Game, Market, parse_csv
from common.nfl.model import NFL, predict_game
from common.stats_model.ratings import replay_ratings
from nfl.orchestrator.target_week import select_target

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

DEFAULT_CSV_URL = "https://github.com/nflverse/nfldata/raw/master/data/games.csv"
MODEL_ID = "nfl-elo-v1"
METRIC_NAMESPACE = "NflPredictor"
METRIC_NAME = "UnpredictedGames"
FETCH_TIMEOUT_SECONDS = 30
_ALLOWED_SCHEMES = ("https://", "file://")


def _now() -> datetime:
    return datetime.now(UTC)


def _utc_z(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def csv_url() -> str:
    return os.environ.get("NFL_GAMES_CSV_URL", DEFAULT_CSV_URL)


def fetch_csv(url: str) -> str:
    """The CSV text at `url` (https or file only). Raises on any failure."""
    if not url.startswith(_ALLOWED_SCHEMES):
        raise ValueError(f"NFL_GAMES_CSV_URL must be https:// or file://, got {url!r}")
    # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected -- scheme allow-listed above; the URL is deploy-time config, not user input
    with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT_SECONDS) as resp:  # noqa: S310
        return resp.read().decode("utf-8")


def rng_seed(match_id: str) -> str:
    """Per-game Monte Carlo seed: a rerun (or a backfill) reproduces the same draw."""
    return f"{MODEL_ID}:{match_id}"


# ---------------------------------------------------------------------------
# nfl_games
# ---------------------------------------------------------------------------

def game_item(game: Game, market: Market | None, scraped_at: str) -> dict:
    item: dict = {
        "matchId": game.match_id,
        "game_id": game.game_id,
        "season": game.season,
        "week": game.week,
        "stage": game.stage,
        "home_team": game.home,
        "away_team": game.away,
        "neutral": game.neutral,
        "played": game.played,
        "scraped_at": scraped_at,
    }
    if game.home_score is not None and game.away_score is not None:
        item["home_score"], item["away_score"] = game.home_score, game.away_score
    if game.kickoff_utc is not None:
        item["kickoff_utc"] = _utc_z(game.kickoff_utc)
    if market is not None:
        lines = {
            "spread_line": None if market.spread_line is None else Decimal(str(market.spread_line)),
            "home_moneyline": market.home_moneyline,
            "away_moneyline": market.away_moneyline,
        }
        item["market"] = {k: v for k, v in lines.items() if v is not None}
    return item


def upsert_games(
    table, games: Iterable[Game], markets: Mapping[str, Market], scraped_at: str
) -> None:
    with table.batch_writer() as batch:
        for game in games:
            batch.put_item(Item=game_item(game, markets.get(game.match_id), scraped_at))


# ---------------------------------------------------------------------------
# nfl_predictions
# ---------------------------------------------------------------------------

def prediction_rows(table, match_id: str) -> list[dict]:
    rows: list[dict] = []
    kwargs: dict = {"KeyConditionExpression": Key("matchId").eq(match_id)}
    while True:
        resp = table.query(**kwargs)
        rows.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            return rows
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def has_ok(rows: Iterable[dict]) -> bool:
    return any(r.get("status") == "OK" for r in rows)


def store_prediction(
    table,
    game: Game,
    ratings: Mapping[str, float],
    *,
    generation: int,
    backfilled: bool,
    now: datetime,
) -> bool:
    """Predict `game` from pre-week `ratings` and write an OK row, or a FAILED row
    if anything goes wrong. Returns True on OK."""
    generated_at = now.isoformat()
    base = {
        "matchId": game.match_id,
        "generatedAt": generated_at,
        "season": game.season,
        "week": game.week,
        "model_used": MODEL_ID,
        "generation": generation,
        "backfilled": backfilled,
        "scraped_at": generated_at,
    }
    try:
        pred = predict_game(game, ratings, random.Random(rng_seed(game.match_id)))
        table.put_item(Item={
            **base,
            "stage": game.stage,
            "predicted_winner": pred.predicted_winner,
            "predicted_margin": pred.predicted_margin,
            "margin_low": pred.margin_low,
            "margin_high": pred.margin_high,
            "home_win_probability": Decimal(str(round(pred.home_win_probability, 4))),
            "confidence": pred.confidence,
            "key_factors": pred.key_factors,
            "reasoning": pred.reasoning,
            "neutral": game.neutral,
            "kickoff_utc": _utc_z(game.kickoff_utc) if game.kickoff_utc else None,
            "status": "OK",
        })
        return True
    except Exception as e:
        logger.error("NFL prediction failed for %s: %s", game.match_id, e, exc_info=True)
        table.put_item(Item={**base, "status": "FAILED", "error": str(e)})
        return False


def _emit_unpredicted(count: int) -> None:
    # The log lines are the source of truth; a CloudWatch hiccup must not abort
    # the run after the predictions are written.
    try:
        boto3.client("cloudwatch").put_metric_data(
            Namespace=METRIC_NAMESPACE,
            MetricData=[{"MetricName": METRIC_NAME, "Value": count, "Unit": "Count"}],
        )
    except Exception:
        logger.exception("Failed to emit %s/%s metric", METRIC_NAMESPACE, METRIC_NAME)


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

def lambda_handler(event: dict, context) -> dict:
    games_table_name = os.environ["NFL_GAMES_TABLE"]
    predictions_table_name = os.environ["NFL_PREDICTIONS_TABLE"]

    games, markets = parse_csv(fetch_csv(csv_url()))
    now = _now()
    target = select_target(games, now)
    ddb = boto3.resource("dynamodb")
    if target.season is not None:
        current = [g for g in games if g.season == target.season]
        upsert_games(ddb.Table(games_table_name), current, markets, now.isoformat())

    for game in target.cancelled:
        logger.warning("%s is unscored more than 72h after kickoff — treated as cancelled",
                       game.match_id)
    if target.blockers:
        logger.warning("Week %s of %s not predicted: waiting on results for %s",
                       target.week, target.season,
                       ", ".join(g.match_id for g in target.blockers))

    predictions = ddb.Table(predictions_table_name)
    ratings = (replay_ratings(games, NFL, before=(target.season, target.week))
               if target.to_predict and target.season is not None and target.week is not None
               else {})
    predicted: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []
    unpredicted = 0
    for game in target.pending:
        rows = prediction_rows(predictions, game.match_id)
        if has_ok(rows):
            skipped.append(game.match_id)
        elif target.blockers:
            unpredicted += 1
        elif store_prediction(predictions, game, ratings, generation=len(rows) + 1,
                              backfilled=False, now=now):
            predicted.append(game.match_id)
        else:
            failed.append(game.match_id)
            unpredicted += 1

    _emit_unpredicted(unpredicted)
    logger.info("NFL %s week %s: predicted %d, already predicted %d, failed %d, unpredicted %d",
                target.season, target.week, len(predicted), len(skipped), len(failed), unpredicted)
    return {
        "season": target.season,
        "week": target.week,
        "predicted": predicted,
        "skipped": skipped,
        "failed": failed,
        "blocked_by": [g.match_id for g in target.blockers],
        "cancelled": [g.match_id for g in target.cancelled],
        "unpredicted": unpredicted,
    }
