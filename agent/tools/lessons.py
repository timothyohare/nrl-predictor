import os
from typing import Any

import boto3


def get_lessons(season: int, team: str | None = None, limit: int = 10, table=None) -> list[dict]:
    """Return recent retrospective lessons for a season, optionally filtered by team slug."""
    tbl = table or boto3.resource("dynamodb").Table(os.environ["RETROSPECTIVES_TABLE"])

    filter_expr = "season = :s"
    expr_values: dict[str, Any] = {":s": season}

    if team:
        filter_expr += " AND contains(matchId, :t)"
        expr_values[":t"] = team.lower()

    response = tbl.scan(
        FilterExpression=filter_expr,
        ExpressionAttributeValues=expr_values,
    )
    items = response.get("Items", [])
    items = [i for i in items if i.get("lesson")]
    items.sort(key=lambda x: x.get("generatedAt", ""), reverse=True)
    return [
        {
            "matchId": i["matchId"],
            "roundNumber": i.get("roundNumber"),
            "lesson": i["lesson"],
            "generatedAt": i.get("generatedAt", ""),
        }
        for i in items[:limit]
    ]
