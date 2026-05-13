import os
import boto3


def get_ladder(season: int, table=None) -> list[dict]:
    tbl = table or boto3.resource("dynamodb").Table(os.environ["TEAMS_TABLE"])
    response = tbl.get_item(Key={"teamId": f"ladder#{season}", "round": "current"})
    item = response.get("Item")
    if not item:
        return []
    positions = item.get("positions", [])
    return sorted(positions, key=lambda p: p["position"])
