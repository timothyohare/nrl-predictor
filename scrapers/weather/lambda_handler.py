"""Weather scraper Lambda — forecasts for every venue in the current round.

EventBridge invokes this with no meaningful payload, so the round is resolved
the same way the orchestrator does: fetch the draw for round "current".
Items are keyed exactly as the agent's get_weather tool reads them:
pk = "weather#{venue}", sk = kickoff UTC date (YYYY-MM-DD).
"""
import logging
import os
from datetime import UTC, datetime
from decimal import Decimal

import boto3

from scrapers.nrl.draw import fetch_draw, parse_draw
from scrapers.weather.venues import VENUES
from scrapers.weather.weather import get_forecast

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def lambda_handler(event: dict, context) -> dict:
    event = event or {}
    season = int(event.get("season") or datetime.now(UTC).year)
    round_number = event.get("round", "current")
    table = boto3.resource("dynamodb").Table(os.environ["WEATHER_TABLE"])
    scraped_at = datetime.now(UTC).isoformat()

    matches = parse_draw(fetch_draw(season, round_number))
    written = 0
    seen: set[tuple[str, str]] = set()
    for match in matches:
        if not match.kick_off or match.match_state == "FullTime":
            continue
        coords = VENUES.get(match.venue)
        if coords is None:
            logger.warning("No coordinates for venue %r (%s) — skipping", match.venue, match.match_id)
            continue
        date = match.kick_off[:10]
        if (match.venue, date) in seen:
            continue
        seen.add((match.venue, date))
        try:
            forecast = get_forecast(match.venue, coords[0], coords[1], date, match.kick_off)
        except Exception:
            logger.warning("No forecast available for %s on %s", match.venue, date, exc_info=True)
            continue
        table.put_item(Item={
            "pk": f"weather#{forecast.venue}",
            "sk": forecast.date,
            **{
                k: Decimal(str(v)) if isinstance(v, float) else v
                for k, v in forecast.__dict__.items()
            },
            "scraped_at": scraped_at,
        })
        written += 1

    logger.info("Wrote %d forecasts for %d matches", written, len(matches))
    return {"matches": len(matches), "written": written}
