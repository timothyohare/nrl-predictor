import os
from datetime import UTC, datetime, timedelta

import boto3

from common.teams import to_slug

_MAX_AGE_HOURS = 48


def get_injury_list(team: str, table=None) -> list[dict]:
    tbl = table or boto3.resource("dynamodb").Table(os.environ["INJURIES_TABLE"])
    cutoff = (datetime.now(UTC) - timedelta(hours=_MAX_AGE_HOURS)).isoformat()
    # scrapers/articles/lambda_handler.py slugs the team before writing the pk
    # ("injury#{team-slug}#{player-slug}") — match on the same slug here.
    prefix = f"injury#{to_slug(team)}#"
    response = tbl.scan(
        FilterExpression="begins_with(pk, :prefix) AND sk > :cutoff",
        ExpressionAttributeValues={":prefix": prefix, ":cutoff": cutoff},
    )
    return response.get("Items", [])
