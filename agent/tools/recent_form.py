import os
import boto3


def get_recent_form(team: str, n: int = 5, table=None) -> list[dict]:
    tbl = table or boto3.resource("dynamodb").Table(os.environ["RESULTS_TABLE"])
    response = tbl.scan(
        FilterExpression="homeTeam = :t OR awayTeam = :t",
        ExpressionAttributeValues={":t": team},
    )
    items = sorted(response.get("Items", []), key=lambda x: x["scoredAt"], reverse=True)
    return items[:n]
