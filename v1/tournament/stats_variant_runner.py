"""Runs the local Elo + Monte Carlo variant for a round — no LLM calls, no Anthropic
API dependency. See docs/plans/10-elo-monte-carlo-predictor.md, Phase 2.

Deliberately does not import v1.agent.graph or anything Claude-related — that's the
whole point of this variant (Phase 1 backtest: 69.6% pick rate vs the season LLM's
63.3%, on data already sitting in the `results` table).
"""
import logging
import random
from datetime import UTC, datetime

from common.match_id import teams_of
from common.stats_model.elo import DEFAULT_HOME_ADVANTAGE
from common.stats_model.predictor import predict_match
from common.stats_model.ratings import compute_ratings_as_of, load_canonical_results

logger = logging.getLogger(__name__)

_N_SIMULATIONS = 10000


def run_stats_variant_for_round(
    variant_id: str,
    match_ids: list[str],
    round_number: int,
    season: int,
    sim_table=None,
    results_table=None,
) -> list[dict]:
    """Predict every match in `match_ids` using ratings as they stood before
    `round_number` (no look-ahead). Returns the simulation prediction records
    written (or that would be written) to `sim_table`.
    """
    results = load_canonical_results(results_table)
    ratings = compute_ratings_as_of(results, round_number, DEFAULT_HOME_ADVANTAGE)

    records = []
    for match_id in match_ids:
        teams = teams_of(match_id)
        if teams is None:
            logger.error("Stats variant %s: could not parse teams from matchId %s", variant_id, match_id)
            continue
        home, away = teams

        rng = random.Random(f"{variant_id}:{match_id}")
        pred = predict_match(home, away, ratings, DEFAULT_HOME_ADVANTAGE, _N_SIMULATIONS, rng)

        record = {
            "pk": f"{match_id}#{variant_id}",
            "matchId": match_id,
            "variantId": variant_id,
            "roundNumber": round_number,
            "season": season,
            "generatedAt": datetime.now(UTC).isoformat(),
            "predicted_winner": pred.predicted_winner,
            "predicted_margin": pred.predicted_margin,
            "confidence": pred.confidence,
            "key_factors": pred.key_factors,
            "reasoning": pred.reasoning[:500],
        }

        if sim_table is not None:
            sim_table.put_item(Item=record)
        records.append(record)

    logger.info(
        "Stats variant %s: wrote %d/%d predictions for round %d",
        variant_id, len(records), len(match_ids), round_number,
    )
    return records
