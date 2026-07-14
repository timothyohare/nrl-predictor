from decimal import Decimal
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

from scrapers.shared.models import Match, WeatherForecast
from scrapers.weather import lambda_handler as handler_module
from scrapers.weather.weather import WeatherDataUnavailable

TABLE = "weather"


def _match(
    venue: str = "Suncorp Stadium",
    match_id: str = "round-19-broncos-v-storm",
    kick_off: str | None = "2026-07-17T09:50:00Z",
    match_state: str = "Upcoming",
) -> Match:
    return Match(
        match_id=match_id,
        home_team="broncos",
        away_team="storm",
        venue=venue,
        round_number=19,
        kick_off=kick_off,
        match_state=match_state,
    )


def _forecast(venue: str = "Suncorp Stadium", date: str = "2026-07-17") -> WeatherForecast:
    return WeatherForecast(
        venue=venue, date=date, hour=9,
        rain_chance_pct=45, rain_mm=2.4, wind_kmh=28, temp_c=17.8,
    )


@pytest.fixture
def weather_table(monkeypatch):
    monkeypatch.setenv("WEATHER_TABLE", TABLE)
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
        yield boto3.resource("dynamodb", region_name="ap-southeast-2").Table(TABLE)


def _run(matches, forecast=None, event=None):
    with patch.object(handler_module, "fetch_draw", return_value={}), \
         patch.object(handler_module, "parse_draw", return_value=matches), \
         patch.object(handler_module, "get_forecast") as forecast_mock:
        if isinstance(forecast, list):
            forecast_mock.side_effect = forecast
        else:
            forecast_mock.return_value = forecast or _forecast()
        result = handler_module.lambda_handler(event or {"season": 2026}, None)
    return result, forecast_mock


def test_writes_forecast_keyed_by_venue_and_kickoff_date(weather_table):
    _run([_match()])
    item = weather_table.get_item(
        Key={"pk": "weather#Suncorp Stadium", "sk": "2026-07-17"}
    ).get("Item")
    assert item is not None
    assert item["venue"] == "Suncorp Stadium"
    assert item["temp_c"] == Decimal("17.8")
    assert item["rain_chance_pct"] == 45
    assert "scraped_at" in item


def test_skips_venue_without_coordinates(weather_table):
    result, forecast_mock = _run([_match(venue="Mystery Park")])
    assert forecast_mock.call_count == 0
    assert result["written"] == 0


def test_forecast_failure_does_not_abort_other_matches(weather_table):
    matches = [
        _match(venue="Suncorp Stadium"),
        _match(venue="AAMI Park", match_id="round-19-storm-v-panthers"),
    ]
    result, _ = _run(
        matches,
        forecast=[WeatherDataUnavailable("no slot"), _forecast(venue="AAMI Park")],
    )
    assert result["written"] == 1
    item = weather_table.get_item(
        Key={"pk": "weather#AAMI Park", "sk": "2026-07-17"}
    ).get("Item")
    assert item is not None


def test_deduplicates_double_header_venue_and_date(weather_table):
    matches = [
        _match(match_id="round-19-broncos-v-storm"),
        _match(match_id="round-19-dolphins-v-titans"),
    ]
    _, forecast_mock = _run(matches)
    assert forecast_mock.call_count == 1


def test_skips_completed_and_kickoffless_matches(weather_table):
    matches = [
        _match(match_state="FullTime"),
        _match(match_id="round-19-eels-v-sharks", kick_off=None),
    ]
    result, forecast_mock = _run(matches)
    assert forecast_mock.call_count == 0
    assert result["written"] == 0
