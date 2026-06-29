"""Tournament scorer Lambda — triggered after match scoring, scores all variant predictions."""
import logging
import os

import boto3

from v1.tournament.variant_scorer import aggregate_variant_season, score_round

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def lambda_handler(event: dict, context) -> dict:
    round_number = event["round"]
    season = event["season"]

    ddb = boto3.resource("dynamodb")
    sim_table = ddb.Table(os.environ["SIMULATION_PREDICTIONS_TABLE"])
    results_table = ddb.Table(os.environ["RESULTS_TABLE"])
    metrics_table = ddb.Table(os.environ["VARIANT_METRICS_TABLE"])

    written = score_round(round_number, season, sim_table, results_table, metrics_table)
    logger.info("Scored round %d: %d variants", round_number, len(written))

    aggregate_variant_season(season, sim_table, results_table, metrics_table)
    logger.info("Season aggregation complete for %d variants", len(written))

    return {"status": "ok", "round": round_number, "variants_scored": len(written)}
