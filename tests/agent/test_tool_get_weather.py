from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

from agent.tools.weather import ToolError, get_weather

TABLE = "weather"


@pytest.fixture
def ddb_table():
    with mock_aws():
        boto3.client("dynamodb", region_name="ap-southeast-2").create_table(
            TableName=TABLE,
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        tbl = boto3.resource("dynamodb", region_name="ap-southeast-2").Table(TABLE)
        tbl.put_item(Item={
            "pk": "weather#Suncorp Stadium",
            "sk": "2026-05-16",
            "venue": "Suncorp Stadium",
            "date": "2026-05-16",
            "hour": 19,
            "rain_chance_pct": 40,
            "rain_mm": Decimal("2.5"),
            "wind_kmh": 22,
            "temp_c": Decimal("18.5"),
            "scraped_at": "2026-05-15T10:00:00Z",
        })
        yield tbl


def test_returns_weather_forecast(ddb_table):
    result = get_weather("Suncorp Stadium", "2026-05-16", table=ddb_table)
    assert result["venue"] == "Suncorp Stadium"
    assert result["rain_chance_pct"] == 40


def test_raises_if_not_found(ddb_table):
    with pytest.raises(ToolError):
        get_weather("AAMI Park", "2026-05-16", table=ddb_table)
