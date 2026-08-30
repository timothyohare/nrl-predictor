"""Tests for common/weather.py — the match-day variance signal for stats-elo-v1
(docs/plans/11-team-sheet-injury-weather-signals.md, Phase 4).
"""
import boto3
import pytest
from moto import mock_aws

from common.weather import (
    PROVISIONAL_BAD_WEATHER_MULTIPLIER,
    is_bad_weather,
    margin_stdev_multiplier_for,
)


def test_heavy_rain_is_bad_weather():
    assert is_bad_weather({"rain_chance_pct": 90, "wind_kmh": 5}) is True


def test_high_wind_is_bad_weather():
    assert is_bad_weather({"rain_chance_pct": 5, "wind_kmh": 55}) is True


def test_mild_forecast_is_not_bad_weather():
    assert is_bad_weather({"rain_chance_pct": 20, "wind_kmh": 15}) is False


def test_missing_fields_are_not_bad_weather():
    assert is_bad_weather({}) is False


@pytest.fixture
def weather_table():
    with mock_aws():
        client = boto3.client("dynamodb", region_name="ap-southeast-2")
        client.create_table(
            TableName="weather",
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
        yield boto3.resource("dynamodb", region_name="ap-southeast-2").Table("weather")


class TestMarginStdevMultiplierFor:
    def test_no_forecast_row_is_inert(self, weather_table):
        assert margin_stdev_multiplier_for(weather_table, "Accor Stadium", "2026-08-30") == 1.0

    def test_bad_weather_forecast_widens_the_multiplier(self, weather_table):
        weather_table.put_item(Item={
            "pk": "weather#Accor Stadium", "sk": "2026-08-30",
            "rain_chance_pct": 90, "wind_kmh": 10, "rain_mm": 12, "temp_c": 14,
        })
        assert margin_stdev_multiplier_for(
            weather_table, "Accor Stadium", "2026-08-30"
        ) == PROVISIONAL_BAD_WEATHER_MULTIPLIER

    def test_mild_forecast_row_is_inert(self, weather_table):
        weather_table.put_item(Item={
            "pk": "weather#Accor Stadium", "sk": "2026-08-30",
            "rain_chance_pct": 10, "wind_kmh": 10, "rain_mm": 0, "temp_c": 22,
        })
        assert margin_stdev_multiplier_for(weather_table, "Accor Stadium", "2026-08-30") == 1.0

    def test_none_table_is_inert(self):
        assert margin_stdev_multiplier_for(None, "Accor Stadium", "2026-08-30") == 1.0

    def test_none_date_is_inert(self, weather_table):
        weather_table.put_item(Item={
            "pk": "weather#Accor Stadium", "sk": "2026-08-30",
            "rain_chance_pct": 90, "wind_kmh": 10, "rain_mm": 12, "temp_c": 14,
        })
        assert margin_stdev_multiplier_for(weather_table, "Accor Stadium", None) == 1.0
