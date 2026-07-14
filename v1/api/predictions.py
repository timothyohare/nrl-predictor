import json
import os
from decimal import Decimal

import boto3

from common.teams import display_name, to_slug


def _serialise(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Not serialisable: {type(obj)}")


def _scan_all(table, **kwargs) -> list[dict]:
    """Full paginated scan — a single scan() call stops at the 1MB page limit,
    which silently drops matches once the table outgrows one page."""
    items: list[dict] = []
    while True:
        response = table.scan(**kwargs)
        items.extend(response.get("Items", []))
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            return items
        kwargs["ExclusiveStartKey"] = last_key


def lambda_handler(event: dict, context) -> dict:
    round_number = int((event.get("pathParameters") or {}).get("round", 0))
    ddb = boto3.resource("dynamodb")
    pred_table = ddb.Table(os.environ["PREDICTIONS_TABLE"])
    retro_table_name = os.environ.get("RETROSPECTIVES_TABLE")
    results_table_name = os.environ.get("RESULTS_TABLE")

    items = _scan_all(
        pred_table,
        FilterExpression="roundNumber = :r AND #s = :ok",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":r": round_number, ":ok": "OK"},
    )
    # Only the most recent prediction per match
    by_match: dict[str, dict] = {}
    for item in items:
        mid = item["matchId"]
        if mid not in by_match or item["generatedAt"] > by_match[mid]["generatedAt"]:
            by_match[mid] = item

    if not by_match:
        return {
            "statusCode": 404,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": f"No predictions for round {round_number}"}),
        }

    # Fetch retrospectives and join by matchId
    retro_by_match: dict[str, dict] = {}
    if retro_table_name:
        try:
            retro_table = ddb.Table(retro_table_name)
            retro_items = _scan_all(
                retro_table,
                FilterExpression="roundNumber = :r",
                ExpressionAttributeValues={":r": round_number},
            )
            for item in retro_items:
                mid = item["matchId"]
                if mid not in retro_by_match or item["generatedAt"] > retro_by_match[mid]["generatedAt"]:
                    retro_by_match[mid] = item
        except Exception:
            pass  # retrospective is non-critical

    # Fetch results and join by matchId — take the most recent scored row
    # per match. The scoring lambda's row is what carries roundNumber, so
    # filtering on roundNumber naturally excludes the raw scrape rows.
    result_by_match: dict[str, dict] = {}
    if results_table_name:
        try:
            results_table = ddb.Table(results_table_name)
            res_items = _scan_all(
                results_table,
                FilterExpression="roundNumber = :r",
                ExpressionAttributeValues={":r": round_number},
            )
            for item in res_items:
                mid = item["matchId"]
                if mid not in result_by_match or item["scoredAt"] > result_by_match[mid]["scoredAt"]:
                    result_by_match[mid] = item
        except Exception:
            pass  # result join is non-critical

    # Fetch odds and join by matchId
    odds_by_match: dict[str, dict] = {}
    odds_table_name = os.environ.get("ODDS_TABLE")
    if odds_table_name:
        try:
            odds_table = ddb.Table(odds_table_name)
            odds_items = _scan_all(
                odds_table,
                FilterExpression="roundNumber = :r",
                ExpressionAttributeValues={":r": round_number},
            )
            for item in odds_items:
                mid = item["matchId"]
                if mid not in odds_by_match or item.get("scrapedAt", "") > odds_by_match[mid].get("scrapedAt", ""):
                    odds_by_match[mid] = item
        except Exception:
            pass  # odds are non-critical

    predictions = sorted(by_match.values(), key=lambda x: x["matchId"])
    for pred in predictions:
        retro = retro_by_match.get(pred["matchId"])
        if retro:
            pred["retrospective"] = {
                "verdict": retro.get("verdict", ""),
                "hit_factors": retro.get("hit_factors", []),
                "missed_factors": retro.get("missed_factors", []),
                "what_actually_happened": retro.get("what_actually_happened", ""),
                "lesson": retro.get("lesson", ""),
                "generated_at": retro.get("generatedAt", ""),
            }
        # Team identity is stored as a slug; expose display names for the frontend
        # alongside the raw slug fields.
        pred["predicted_winner_name"] = display_name(to_slug(pred.get("predicted_winner", "")))
        result = result_by_match.get(pred["matchId"])
        if result:
            pred["result"] = {
                "winner": result.get("winner", ""),
                "winner_name": display_name(to_slug(result.get("winner", ""))),
                "homeTeam": result.get("homeTeam", ""),
                "homeTeam_name": display_name(to_slug(result.get("homeTeam", ""))),
                "awayTeam": result.get("awayTeam", ""),
                "awayTeam_name": display_name(to_slug(result.get("awayTeam", ""))),
                "homeScore": result.get("homeScore", 0),
                "awayScore": result.get("awayScore", 0),
                "margin": result.get("margin", 0),
            }
        odds = odds_by_match.get(pred["matchId"])
        if odds:
            pred["odds"] = {
                "market_favourite": odds.get("market_favourite", ""),
                "market_margin": float(odds.get("market_margin", 0)),
                "home_odds": float(odds.get("home_odds", 0)),
                "away_odds": float(odds.get("away_odds", 0)),
                "implied_home_prob": float(odds.get("implied_home_prob", 0)),
                "implied_away_prob": float(odds.get("implied_away_prob", 0)),
            }
            # Outlier: prediction disagrees with market on winner or margin differs by >6
            pred_winner = to_slug(pred.get("predicted_winner", ""))
            market_fav = to_slug(odds.get("market_favourite", ""))
            pred_margin = int(pred.get("predicted_margin", 0))
            market_margin = float(odds.get("market_margin", 0))
            pred["is_outlier"] = (
                pred_winner != market_fav
                or abs(pred_margin - market_margin) > 6
            )

    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "Cache-Control": "public, max-age=300",
        },
        "body": json.dumps(predictions, default=_serialise),
    }
