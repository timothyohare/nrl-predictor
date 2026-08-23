"""Tournament orchestrator Lambda — fans out to per-variant worker Lambdas."""
import json
import logging
import os
from datetime import UTC, datetime

import boto3

from common.dynamo import scan_all
from scrapers.nrl.draw import fetch_draw, parse_draw
from scrapers.shared.models import Match

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_STAGGER_PER_CALL_SECONDS = 12  # max 5 calls/min at 10K tokens/call stays under 50K/min


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _kickoff_pending(match: Match, now: datetime) -> bool:
    """False once a match has finished or its kickoff has already passed.

    This Lambda now runs several times a week (mirroring the main
    predictor's Tue/Thu/Fri/Sat cadence) instead of once on Saturday
    morning, so a later run must not "predict" a match that's already been
    played — that's hindsight, not a prediction, and silently inflates
    variant_metrics.
    """
    if match.match_state == "FullTime":
        return False
    if match.kick_off:
        try:
            kickoff_dt = datetime.fromisoformat(match.kick_off.replace("Z", "+00:00"))
        except ValueError:
            return True
        if kickoff_dt <= now:
            return False
    return True


def lambda_handler(event: dict, context) -> dict:
    season = event["season"]
    round_input = event["round"]
    match_ids = event.get("matchIds", [])

    ddb = boto3.resource("dynamodb")

    if match_ids:
        round_number = round_input
    else:
        # Scheduled path: no matchIds supplied, so scrape the draw ourselves
        # (same source of truth the main orchestrator already used) rather
        # than silently no-oping.
        round_for_fetch = round_input if round_input == "current" else int(round_input)
        raw_draw = fetch_draw(season, round_for_fetch)
        matches = parse_draw(raw_draw)
        if not matches:
            logger.warning("No matches parsed for season=%s round=%s", season, round_input)
            return {"status": "ok", "variants_launched": 0}
        round_number = matches[0].round_number

        now = _utcnow()
        pending = [m for m in matches if _kickoff_pending(m, now)]
        skipped_started = len(matches) - len(pending)
        if skipped_started:
            logger.warning(
                "Skipping %d already-started/finished match(es) for round %s", skipped_started, round_number
            )

        # A match already predicted by an earlier run this week must not be
        # predicted again — score_round() sums every simulation_predictions
        # row for the round, so a duplicate row double-counts that match.
        sim_table = ddb.Table(os.environ["SIMULATION_PREDICTIONS_TABLE"])
        already_predicted = {
            item["matchId"]
            for item in scan_all(
                sim_table,
                FilterExpression="roundNumber = :r AND season = :s",
                ExpressionAttributeValues={":r": round_number, ":s": season},
            )
        }
        pending = [m for m in pending if m.match_id not in already_predicted]

        if not pending:
            logger.info(
                "No pending matches to predict for round %s (all started or already predicted)", round_number
            )
            return {"status": "ok", "variants_launched": 0}
        match_ids = [m.match_id for m in pending]

    variants_table = ddb.Table(os.environ["PROMPT_VARIANTS_TABLE"])

    # Get active variants (scan is fine — table is small)
    resp = variants_table.scan(
        FilterExpression="#a = :t",
        ExpressionAttributeNames={"#a": "active"},
        ExpressionAttributeValues={":t": True},
    )
    variants = resp.get("Items", [])

    if not variants:
        logger.warning("No active variants found")
        return {"status": "ok", "variants_launched": 0}

    n_variants = len(variants)
    # Each variant's first call is offset so calls interleave rather than bunch:
    # variant i starts at i * STAGGER_PER_CALL_SECONDS, then sleeps n * STAGGER seconds between matches
    stagger_between_matches = n_variants * _STAGGER_PER_CALL_SECONDS

    lambda_client = boto3.client("lambda")
    worker_fn = os.environ["TOURNAMENT_WORKER_FUNCTION_ARN"]

    for i, variant in enumerate(variants):
        payload = {
            "variantId": variant["variantId"],
            "variantVersion": variant["version"],
            "matchIds": match_ids,
            "round": round_number,
            "season": season,
            "initialDelaySeconds": i * _STAGGER_PER_CALL_SECONDS,
            "staggerSeconds": stagger_between_matches,
        }
        lambda_client.invoke(
            FunctionName=worker_fn,
            InvocationType="Event",  # async — fire and forget
            Payload=json.dumps(payload),
        )
        logger.info(
            "Launched worker for variant %s (delay=%ds)", variant["variantId"], payload["initialDelaySeconds"]
        )

    return {"status": "ok", "variants_launched": n_variants, "matches": len(match_ids)}
