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
    table = boto3.resource("dynamodb").Table(os.environ["PREDICTIONS_TABLE"])

    response = table.scan(
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

    predictions = sorted(by_match.values(), key=lambda x: x["matchId"])

    if not predictions:
        return {
            "statusCode": 404,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": f"No predictions for round {round_number}"}),
        }

    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "Cache-Control": "public, max-age=300",
        },
        "body": json.dumps(predictions, default=_serialise),
    }
