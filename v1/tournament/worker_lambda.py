"""Tournament worker Lambda — runs one variant across all matches for a round.

Dispatches on the variant's `variant_type` field: "prompt" (default, for
backward compatibility with the 8 variants seeded before this field existed)
runs the LLM agent; "stats_model" runs the local Elo + Monte Carlo predictor
with no external API calls at all. See docs/plans/10-elo-monte-carlo-predictor.md.
"""
import logging
import os
import time

import boto3

from v1.tournament.stats_variant_runner import run_stats_variant_for_round
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

    variant_type = variant.get("variant_type", "prompt")

    if variant_type == "stats_model":
        # No Anthropic API call, so nothing to rate-limit — skip the stagger
        # that the LLM path needs to stay under the account's token/min cap.
        results_table = ddb.Table(os.environ["RESULTS_TABLE"])
        teams_table = ddb.Table(os.environ["TEAMS_TABLE"])
        injuries_table = ddb.Table(os.environ["INJURIES_TABLE"])
        weather_table = ddb.Table(os.environ["WEATHER_TABLE"])
        results = run_stats_variant_for_round(
            variant_id=variant_id,
            match_ids=match_ids,
            round_number=round_number,
            season=season,
            sim_table=sim_table,
            results_table=results_table,
            teams_table=teams_table,
            injuries_table=injuries_table,
            weather_table=weather_table,
        )
    else:
        # Stagger this worker's first call relative to other workers — only
        # meaningful for the LLM path, which shares the account rate limit.
        if initial_delay > 0:
            logger.info("Variant %s: waiting %ds before first call", variant_id, initial_delay)
            time.sleep(initial_delay)

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
