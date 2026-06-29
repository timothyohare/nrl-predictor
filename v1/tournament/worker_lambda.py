"""Tournament worker Lambda — runs one prompt variant across all matches for a round."""
import logging
import os
import time

import boto3

from v1.tournament.variant_runner import run_variant_for_round

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def lambda_handler(event: dict, context) -> dict:
    variant_id = event["variantId"]
    match_ids = event["matchIds"]
    round_number = event["round"]
    season = event["season"]
    initial_delay = event.get("initialDelaySeconds", 0)
    stagger_seconds = event.get("staggerSeconds", 96)

    # Stagger this worker's first call relative to other workers
    if initial_delay > 0:
        logger.info("Variant %s: waiting %ds before first call", variant_id, initial_delay)
        time.sleep(initial_delay)

    ddb = boto3.resource("dynamodb")
    variants_table = ddb.Table(os.environ["PROMPT_VARIANTS_TABLE"])
    sim_table = ddb.Table(os.environ["SIMULATION_PREDICTIONS_TABLE"])

    # Load the variant
    resp = variants_table.get_item(
        Key={"variantId": variant_id, "version": event["variantVersion"]}
    )
    variant = resp.get("Item")
    if not variant:
        logger.error("Variant not found: %s @ %s", variant_id, event.get("variantVersion"))
        return {"status": "error", "message": "variant not found"}

    results = run_variant_for_round(
        variant=variant,
        match_ids=match_ids,
        round_number=round_number,
        season=season,
        stagger_seconds=stagger_seconds,
        sim_table=sim_table,
    )

    logger.info("Variant %s: wrote %d/%d predictions", variant_id, len(results), len(match_ids))
    return {"status": "ok", "variantId": variant_id, "predictions": len(results)}
