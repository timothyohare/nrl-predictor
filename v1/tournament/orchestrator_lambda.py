"""Tournament orchestrator Lambda — fans out to per-variant worker Lambdas."""
import json
import logging
import os

import boto3

from scrapers.nrl.draw import fetch_draw, parse_draw

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_STAGGER_PER_CALL_SECONDS = 12  # max 5 calls/min at 10K tokens/call stays under 50K/min


def lambda_handler(event: dict, context) -> dict:
    season = event["season"]
    round_input = event["round"]
    match_ids = event.get("matchIds", [])

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
        match_ids = [m.match_id for m in matches]
        round_number = matches[0].round_number

    ddb = boto3.resource("dynamodb")
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
            "variantVersion": int(variant["version"]),
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
