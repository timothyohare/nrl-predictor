import os
from datetime import UTC, datetime, timedelta

import boto3
from langchain_core.tools import tool

from common.dynamo import scan_all

_MAX_AGE_HOURS = 48


def _get_injury_list(team: str, table=None) -> list[dict]:
    tbl = table or boto3.resource("dynamodb").Table(os.environ["INJURIES_TABLE"])
    cutoff = (datetime.now(UTC) - timedelta(hours=_MAX_AGE_HOURS)).isoformat()
    prefix = f"injury#{team}#"
    return scan_all(
        tbl,
        FilterExpression="begins_with(pk, :prefix) AND sk > :cutoff",
        ExpressionAttributeValues={":prefix": prefix, ":cutoff": cutoff},
    )


@tool
def get_injury_list(team: str) -> list[dict]:
    """Returns current injury/unavailability list for a team."""
    return _get_injury_list(team=team)
