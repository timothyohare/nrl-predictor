import json
from pathlib import Path
from unittest.mock import patch

import pytest

from scrapers.shared.models import WeatherForecast
from scrapers.weather.weather import (
    WeatherDataUnavailable,
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
