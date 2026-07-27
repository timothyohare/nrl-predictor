import os
from typing import Any

import boto3

from common.teams import to_slug


def get_lessons(season: int, team: str | None = None, limit: int = 10, table=None) -> list[dict]:
    """Return recent retrospective lessons for a season, optionally filtered by team slug."""
    tbl = table or boto3.resource("dynamodb").Table(os.environ["RETROSPECTIVES_TABLE"])

    filter_expr = "season = :s"
    expr_values: dict[str, Any] = {":s": season}

    if team:
        filter_expr += " AND contains(matchId, :t)"
        # matchId is round-{N}-{home-slug}-v-{away-slug} (hyphenated slugs) —
        # .lower() alone breaks multi-word nicknames ("Sea Eagles" -> "sea
        # eagles", a space, never matches "sea-eagles" in the matchId).
        expr_values[":t"] = to_slug(team)

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
