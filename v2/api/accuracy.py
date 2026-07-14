import json
import os
from decimal import Decimal

import boto3


def _serialise(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Not serialisable: {type(obj)}")


def lambda_handler(event: dict, context) -> dict:
    table = boto3.resource("dynamodb").Table(os.environ["METRICS_TABLE"])
    items = []
    kwargs: dict = {}
    while True:
        response = table.scan(**kwargs)
        items.extend(response.get("Items", []))
        if "LastEvaluatedKey" not in response:
            break
        kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]

    season = [i for i in items if i["period"].endswith("-season")]
    rounds = [i for i in items if "-round-" in i["period"]]

    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "Cache-Control": "no-store",
        },
        "body": json.dumps({"season": season, "rounds": rounds}, default=_serialise),
    }
