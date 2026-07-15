"""
Round coverage check — runs after the orchestrator's fan-out has had time to
settle and flags matches with no OK prediction. A FAILED-only match silently
disappears from the site (the API serves only OK rows), so this is the alarm
signal for an under-predicted round.
"""
import logging
import os

import boto3
from boto3.dynamodb.conditions import Key

from scrapers.nrl.draw import fetch_draw, parse_draw

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

METRIC_NAMESPACE = "NrlPredictor"
METRIC_NAME = "MissingPredictions"


def _has_ok_prediction(table, match_id: str) -> bool:
    response = table.query(KeyConditionExpression=Key("matchId").eq(match_id))
    return any(item.get("status") == "OK" for item in response.get("Items", []))


def lambda_handler(event: dict, context) -> dict:
    season = int(event.get("season", 2026))
    round_input = event.get("round", "current")
    round_for_fetch = round_input if round_input == "current" else int(round_input)

    matches = parse_draw(fetch_draw(season, round_for_fetch))
    if not matches:
        logger.warning("Coverage check: no matches parsed for season=%s round=%s",
                       season, round_input)
        return {"round": None, "matches": 0, "ok": 0, "missing": []}

    round_number = matches[0].round_number
    table = boto3.resource("dynamodb").Table(os.environ["PREDICTIONS_TABLE"])
    missing = [m.match_id for m in matches if not _has_ok_prediction(table, m.match_id)]
    ok_count = len(matches) - len(missing)

    boto3.client("cloudwatch").put_metric_data(
        Namespace=METRIC_NAMESPACE,
        MetricData=[{
            "MetricName": METRIC_NAME,
            "Value": len(missing),
            "Unit": "Count",
        }],
    )

    if missing:
        logger.warning(
            "Round %s under-predicted: %d/%d matches have an OK prediction; missing: %s",
            round_number, ok_count, len(matches), ", ".join(sorted(missing)),
        )
    else:
        logger.info("Round %s fully covered: %d/%d OK", round_number, ok_count, len(matches))

    return {
        "round": round_number,
        "matches": len(matches),
        "ok": ok_count,
        "missing": missing,
    }
