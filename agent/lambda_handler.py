import logging
import os
from datetime import datetime, timezone

import boto3

from agent.budget import BudgetExceeded, check_budget
from agent.graph import run_agent
from agent.prompt import PROMPT_VERSION
from agent.tools.lessons import get_lessons

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def lambda_handler(event: dict, context) -> None:
    match_id = event["matchId"]
    # Fetch recent lessons from retrospectives to inject into the prompt
    season = event.get("season", datetime.now(timezone.utc).year)
    lessons = []
    retro_table_name = os.environ.get("RETROSPECTIVES_TABLE")
    if retro_table_name:
        try:
            retro_table = boto3.resource("dynamodb").Table(retro_table_name)
            lessons = get_lessons(season=season, limit=5, table=retro_table)
            logger.info("Injecting %d lessons into prompt for %s", len(lessons), match_id)
        except Exception:
            logger.warning("Failed to fetch lessons for %s", match_id, exc_info=True)

    match_context = {
        "round": event.get("round"),
        "is_finals": event.get("is_finals", False),
        "is_high_impact_change": event.get("is_high_impact_change", False),
        "lessons": lessons,
    }
    table_name = os.environ["PREDICTIONS_TABLE"]
    budget_usd = float(os.environ.get("MONTHLY_BUDGET_USD", "18"))
    table = boto3.resource("dynamodb").Table(table_name)
    generated_at = datetime.now(timezone.utc).isoformat()

    try:
        check_budget(threshold_usd=budget_usd)
    except BudgetExceeded as e:
        logger.warning("Budget exceeded — serving cached prediction: %s", e)
        _write_cached_with_staleness(table, match_id, generated_at)
        return

    try:
        prediction = run_agent(match_id, match_context)
        prediction["matchId"] = match_id
        prediction["generatedAt"] = prediction.get("generated_at", generated_at)
        prediction["roundNumber"] = match_context.get("round")
        prediction["staleness_flag"] = False
        prediction["status"] = "OK"
        prediction["prompt_version"] = PROMPT_VERSION
        # Track which generation this is (1 = first prediction, 2 = update, etc.)
        existing = table.query(
            KeyConditionExpression="matchId = :m",
            FilterExpression="#s = :ok",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":m": match_id, ":ok": "OK"},
            Select="COUNT",
        )
        prediction["generation"] = existing.get("Count", 0) + 1
        table.put_item(Item=prediction)
        logger.info("Prediction written for %s", match_id)
    except Exception as e:
        logger.error("Agent failed for %s: %s", match_id, e, exc_info=True)
        table.put_item(Item={
            "matchId": match_id,
            "generatedAt": generated_at,
            "status": "FAILED",
            "error": str(e),
        })


def _write_cached_with_staleness(table, match_id: str, generated_at: str) -> None:
    response = table.query(
        KeyConditionExpression="matchId = :m",
        ExpressionAttributeValues={":m": match_id},
        ScanIndexForward=False,
        Limit=1,
    )
    items = response.get("Items", [])
    if items:
        cached = dict(items[0])
        cached["generatedAt"] = generated_at
        cached["staleness_flag"] = True
        cached["status"] = "STALE"
        table.put_item(Item=cached)
    else:
        table.put_item(Item={
            "matchId": match_id,
            "generatedAt": generated_at,
            "status": "BUDGET_EXCEEDED",
            "staleness_flag": True,
        })
