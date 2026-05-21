import json
import os
from decimal import Decimal

import boto3


def _serialise(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Not serialisable: {type(obj)}")


def lambda_handler(event: dict, context) -> dict:
    round_number = int((event.get("pathParameters") or {}).get("round", 0))
    ddb = boto3.resource("dynamodb")
    pred_table = ddb.Table(os.environ["PREDICTIONS_TABLE"])
    retro_table_name = os.environ.get("RETROSPECTIVES_TABLE")

    response = pred_table.scan(
        FilterExpression="roundNumber = :r AND #s = :ok",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":r": round_number, ":ok": "OK"},
    )
    items = response.get("Items", [])
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
            retro_resp = retro_table.scan(
                FilterExpression="roundNumber = :r",
                ExpressionAttributeValues={":r": round_number},
            )
            for item in retro_resp.get("Items", []):
                mid = item["matchId"]
                if mid not in retro_by_match or item["generatedAt"] > retro_by_match[mid]["generatedAt"]:
                    retro_by_match[mid] = item
        except Exception:
            pass  # retrospective is non-critical

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

    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "Cache-Control": "public, max-age=300",
        },
        "body": json.dumps(predictions, default=_serialise),
    }
