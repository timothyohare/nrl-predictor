import os
import boto3


class ToolError(Exception):
    pass


def get_weather(venue: str, date: str, table=None) -> dict:
    tbl = table or boto3.resource("dynamodb").Table(os.environ["WEATHER_TABLE"])
    response = tbl.get_item(Key={"pk": f"weather#{venue}", "sk": date})
    item = response.get("Item")
    if not item:
        raise ToolError(f"No weather forecast for {venue} on {date}")
    return item
