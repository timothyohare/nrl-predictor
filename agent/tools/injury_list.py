import os
from datetime import datetime, timezone, timedelta

import boto3
from boto3.dynamodb.conditions import Key

_MAX_AGE_HOURS = 48


def get_injury_list(team: str, table=None) -> list[dict]:
    tbl = table or boto3.resource("dynamodb").Table(os.environ["INJURIES_TABLE"])
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=_MAX_AGE_HOURS)).isoformat()
    prefix = f"injury#{team}#"
    response = tbl.scan(
        FilterExpression="begins_with(pk, :prefix) AND sk > :cutoff",
        ExpressionAttributeValues={":prefix": prefix, ":cutoff": cutoff},
    )
    return response.get("Items", [])
