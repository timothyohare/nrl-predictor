import json
from pathlib import Path
from unittest.mock import patch

import pytest

from scrapers.shared.http_client import ScraperError
from scrapers.shared.models import WeatherForecast
from scrapers.weather.weather import (
    WeatherDataUnavailable,
    fetch_bom_hourly,
    fetch_open_meteo,
    get_forecast,
    get_geohash,
    parse_bom_hourly,
    parse_open_meteo,
)

OM_FIXTURE = Path(__file__).parent.parent / "fixtures" / "open_meteo_response.json"
BOM_HOURLY_FIXTURE = Path(__file__).parent.parent / "fixtures" / "bom_hourly_response.json"


@pytest.fixture
def om_data():
    return json.loads(OM_FIXTURE.read_text())


@pytest.fixture
def bom_hourly_data():
    return json.loads(BOM_HOURLY_FIXTURE.read_text())


# ── Open-Meteo ────────────────────────────────────────────────────────────────

def test_parse_open_meteo_returns_weather_forecast(om_data):
    result = parse_open_meteo(om_data, target_date="2026-05-16", target_hour=9, venue="AAMI Park")
    assert isinstance(result, WeatherForecast)


def test_parse_open_meteo_selects_correct_hour(om_data):
    result = parse_open_meteo(om_data, target_date="2026-05-16", target_hour=9, venue="AAMI Park")
    assert result.hour == 9
    assert result.rain_chance_pct == 45
    assert result.wind_kmh == 28
    assert result.temp_c == pytest.approx(17.8)


def test_parse_open_meteo_rain_mm_is_max_of_that_hour(om_data):
    result = parse_open_meteo(om_data, target_date="2026-05-16", target_hour=9, venue="AAMI Park")
    assert result.rain_mm == pytest.approx(2.4)


def test_parse_open_meteo_raises_for_out_of_range_date(om_data):
    with pytest.raises(WeatherDataUnavailable):
        parse_open_meteo(om_data, target_date="2026-05-25", target_hour=9, venue="AAMI Park")


# ── BOM hourly ────────────────────────────────────────────────────────────────

def test_parse_bom_hourly_returns_weather_forecast(bom_hourly_data):
    result = parse_bom_hourly(bom_hourly_data, target_utc_time="2026-05-16T09:00:00Z", venue="Suncorp Stadium")
    assert isinstance(result, WeatherForecast)


def test_parse_bom_hourly_maps_fields(bom_hourly_data):
    result = parse_bom_hourly(bom_hourly_data, target_utc_time="2026-05-16T09:00:00Z", venue="Suncorp Stadium")
    assert result.rain_chance_pct == 50
    assert result.rain_mm == pytest.approx(3.0)
    assert result.wind_kmh == 28
    assert result.temp_c == 18


def test_parse_bom_hourly_raises_for_missing_slot(bom_hourly_data):
    with pytest.raises(WeatherDataUnavailable):
        parse_bom_hourly(bom_hourly_data, target_utc_time="2026-05-17T15:00:00Z", venue="Suncorp Stadium")


# ── Geohash truncation ────────────────────────────────────────────────────────

def test_get_geohash_returns_6_chars():
    mock_response = {"data": [{"geohash": "r3dp2x8"}]}
    with patch("scrapers.weather.weather.get_with_retry", return_value=(200, json.dumps(mock_response))):
        result = get_geohash(-33.8688, 151.2093)
    assert len(result) == 6
    assert result == "r3dp2x"


# ── fetch_bom_hourly / fetch_open_meteo (HTTP wrappers) ───────────────────────

def test_fetch_bom_hourly_truncates_geohash_then_fetches_hourly(bom_hourly_data):
    # First call is the location search (7-char geohash), second is the hourly
    # endpoint which must be hit with the 6-char truncation.
    search_body = json.dumps({"data": [{"geohash": "r1r0fsn"}]})
    with patch(
        "scrapers.weather.weather.get_with_retry",
        side_effect=[(200, search_body), (200, json.dumps(bom_hourly_data))],
    ) as mock_get:
        result = fetch_bom_hourly(-27.4698, 153.0251)

    assert result == bom_hourly_data
    hourly_url = mock_get.call_args_list[1].args[0]
    assert "/locations/r1r0fs/" in hourly_url  # truncated to 6 chars


def test_fetch_open_meteo_returns_parsed_json(om_data):
    with patch(
        "scrapers.weather.weather.get_with_retry",
        return_value=(200, json.dumps(om_data)),
    ) as mock_get:
        result = fetch_open_meteo(-37.8136, 144.9631)

    assert result == om_data
    assert "api.open-meteo.com" in mock_get.call_args.args[0]


# ── get_forecast: BOM primary, Open-Meteo fallback ───────────────────────────

def test_get_forecast_uses_bom_when_available(bom_hourly_data):
    with patch("scrapers.weather.weather.fetch_bom_hourly", return_value=bom_hourly_data) as bom_mock, \
         patch("scrapers.weather.weather.fetch_open_meteo") as om_mock:
        result = get_forecast(
            venue="Suncorp Stadium",
            lat=-27.4698,
            lon=153.0251,
            date="2026-05-16",
            kickoff_utc="2026-05-16T09:00:00Z",
        )

    assert isinstance(result, WeatherForecast)
    assert result.rain_chance_pct == 50  # BOM fixture value
    bom_mock.assert_called_once()
    om_mock.assert_not_called()


def test_get_forecast_falls_back_to_open_meteo_when_bom_errors(om_data):
    # BOM hourly endpoint returns a non-200 -> get_with_retry raises ScraperError.
    search_body = json.dumps({"data": [{"geohash": "r1r0fsn"}]})
    with patch(
        "scrapers.weather.weather.get_with_retry",
        side_effect=[
            (200, search_body),
            ScraperError("Client error 503 fetching BOM hourly"),
            (200, json.dumps(om_data)),
        ],
    ):
        result = get_forecast(
            venue="AAMI Park",
            lat=-37.8136,
            lon=144.9631,
            date="2026-05-16",
            kickoff_utc="2026-05-16T09:00:00Z",
        )

    assert isinstance(result, WeatherForecast)
    assert result.venue == "AAMI Park"
    assert result.hour == 9
    assert result.rain_chance_pct == 45  # Open-Meteo fixture value


def test_get_forecast_falls_back_when_geohash_lookup_is_malformed(om_data):
    # Location search returns no data rows -> get_geohash raises IndexError,
    # which get_forecast's bare `except` also catches.
    with patch(
        "scrapers.weather.weather.get_with_retry",
        side_effect=[(200, json.dumps({"data": []})), (200, json.dumps(om_data))],
    ):
        result = get_forecast(
            venue="AAMI Park",
            lat=-37.8136,
            lon=144.9631,
            date="2026-05-16",
            kickoff_utc="2026-05-16T09:00:00Z",
        )

    assert isinstance(result, WeatherForecast)
    assert result.rain_chance_pct == 45


def test_get_forecast_raises_when_both_providers_fail():
    # BOM raises (caught), then Open-Meteo also raises -> propagates uncaught.
    search_body = json.dumps({"data": [{"geohash": "r1r0fsn"}]})
    with patch(
        "scrapers.weather.weather.get_with_retry",
        side_effect=[
            (200, search_body),
            ScraperError("BOM down"),
            ScraperError("Open-Meteo down"),
        ],
    ):
        with pytest.raises(ScraperError):
            get_forecast(
                venue="AAMI Park",
                lat=-37.8136,
                lon=144.9631,
                date="2026-05-16",
                kickoff_utc="2026-05-16T09:00:00Z",
            )
