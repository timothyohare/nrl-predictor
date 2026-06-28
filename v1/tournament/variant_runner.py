"""Runs a single prompt variant for a set of matches."""
import logging
import time
from datetime import UTC, datetime

from v1.agent.graph import run_agent

logger = logging.getLogger(__name__)


def run_variant_prediction(
    match_id: str,
    variant: dict,
    match_context: dict,
    client=None,
    sim_table=None,
) -> dict:
    """Run the agent for one match using a variant's prompt. Returns the simulation prediction record."""
    prediction = run_agent(
        match_id,
        match_context,
        client=client,
        system_prompt=variant["prompt_template"],
    )

    record = {
        "pk": f"{match_id}#{variant['variantId']}",
        "matchId": match_id,
        "variantId": variant["variantId"],
        "generatedAt": datetime.now(UTC).isoformat(),
        "predicted_winner": prediction.get("predicted_winner", ""),
        "predicted_margin": int(prediction.get("predicted_margin", 0)),
        "confidence": prediction.get("confidence", "MEDIUM"),
        "reasoning": (prediction.get("reasoning", "") or "")[:500],
    }

    if sim_table is not None:
        sim_table.put_item(Item=record)
        logger.info("Wrote simulation prediction for %s / %s", match_id, variant["variantId"])

    return record


def run_variant_for_round(
    variant: dict,
    match_ids: list[str],
    round_number: int,
    season: int,
    stagger_seconds: int = 96,
    client=None,
    sim_table=None,
) -> list[dict]:
    """Run a variant's predictions for all matches in a round with staggered API calls."""
    results = []
    match_context = {"round": round_number, "season": season}

    for i, match_id in enumerate(match_ids):
        if i > 0:
            time.sleep(stagger_seconds)
        try:
            result = run_variant_prediction(
                match_id, variant, match_context, client=client, sim_table=sim_table
            )
            results.append(result)
        except Exception as e:
            logger.error("Variant %s failed for %s: %s", variant["variantId"], match_id, e)

    return results
