import logging
import os
from datetime import datetime, timezone

import boto3

from scoring.metrics import aggregate_round
from scoring.scorer import score_prediction

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def lambda_handler(event: dict, context) -> None:
    match_id = event["matchId"]
    round_number = event["round"]
    season = event["season"]

    pred_table = boto3.resource("dynamodb").Table(os.environ["PREDICTIONS_TABLE"])
    results_table = boto3.resource("dynamodb").Table(os.environ["RESULTS_TABLE"])
    metrics_table = boto3.resource("dynamodb").Table(os.environ["METRICS_TABLE"])
    scored_at = datetime.now(timezone.utc).isoformat()

    try:
        scored = score_prediction(match_id, results_table, pred_table)
        results_table.put_item(Item={
            "matchId": match_id,
            "scoredAt": scored_at,
            "correct_pick": scored.correct_pick,
            "predicted_margin_error": scored.predicted_margin_error,
            "within_6_pts": scored.within_6_pts,
            "within_12_pts": scored.within_12_pts,
            "brier_component": str(scored.brier_component),
            "roundNumber": round_number,
            "season": season,
            "matchState": "FullTime",
        })
        logger.info("Scored %s: correct=%s margin_err=%s", match_id, scored.correct_pick, scored.predicted_margin_error)
        aggregate_round(round_number, season, results_table, metrics_table)
    except Exception as e:
        logger.error("Scoring failed for %s: %s", match_id, e, exc_info=True)
        raise
