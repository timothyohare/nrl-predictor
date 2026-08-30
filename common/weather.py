"""Match-day weather signal for `stats-elo-v1`
(docs/plans/11-team-sheet-injury-weather-signals.md, Phase 4).

Unlike the team-sheet/injury signals, weather doesn't say who's better — it
affects how noisy the outcome is. Bad weather widens the simulated margin
distribution (`common.stats_model.simulate.simulate_match`'s
`margin_stdev_multiplier`) rather than shifting a rating.
"""
from __future__ import annotations

# Provisional thresholds/multiplier — only ~52 rows / ~5 weeks of `weather`
# history exist (2026-08-27), far short of the rounds 12-24 backtest window
# the core Elo/margin model was fit against. Refit in Phase 5 of
# docs/plans/11-team-sheet-injury-weather-signals.md.
_RAIN_CHANCE_THRESHOLD_PCT = 60
_WIND_THRESHOLD_KMH = 40
PROVISIONAL_BAD_WEATHER_MULTIPLIER = 1.3


def is_bad_weather(forecast: dict) -> bool:
    """True if a forecast dict (rain_chance_pct/wind_kmh, either optional)
    crosses the (provisional) bad-weather thresholds."""
    rain_chance = forecast.get("rain_chance_pct")
    wind = forecast.get("wind_kmh")
    return (rain_chance is not None and rain_chance >= _RAIN_CHANCE_THRESHOLD_PCT) or (
        wind is not None and wind >= _WIND_THRESHOLD_KMH
    )


def margin_stdev_multiplier_for(weather_table, venue: str, date: str | None) -> float:
    """1.0 (inert) unless a forecast exists for `venue`/`date` and it crosses
    the bad-weather threshold. Fails open — no `weather_table`, no `date`, or
    no matching row all resolve to 1.0, never an error. `date` is the
    kickoff date (YYYY-MM-DD), matching how scrapers/weather/lambda_handler.py
    keys forecasts (`pk=weather#{venue}`, `sk=date`).
    """
    if weather_table is None or not date:
        return 1.0
    item = weather_table.get_item(Key={"pk": f"weather#{venue}", "sk": date}).get("Item")
    if item is None or not is_bad_weather(item):
        return 1.0
    return PROVISIONAL_BAD_WEATHER_MULTIPLIER
