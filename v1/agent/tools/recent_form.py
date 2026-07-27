import os

import boto3

from common.teams import to_slug
from v1.agent.tools.momentum import calculate_momentum


def get_recent_form(team: str, n: int = 5, table=None, exclude_match_id: str | None = None) -> dict:
    tbl = table or boto3.resource("dynamodb").Table(os.environ["RESULTS_TABLE"])
    # Match on the canonical slug so any inbound form resolves, and so mixed stored forms
    # (nickname pre-migration, slug after) both match. Filter client-side.
    slug = to_slug(team)
    items = [
        i for i in tbl.scan().get("Items", [])
        if slug in (to_slug(i.get("homeTeam", "")), to_slug(i.get("awayTeam", "")))
        and i.get("matchId") != exclude_match_id
    ]
    items = sorted(items, key=lambda x: x["scoredAt"], reverse=True)
    results = items[:n]
    momentum = calculate_momentum(results, team=team)
    return {
        "results": results,
        "momentum": momentum,
    }
