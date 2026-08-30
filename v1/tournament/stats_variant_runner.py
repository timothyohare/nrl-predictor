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
from common.players import has_spine_player_ruled_out, injury_adjustment
from common.stats_model.elo import DEFAULT_HOME_ADVANTAGE
from common.stats_model.predictor import predict_match
from common.stats_model.ratings import compute_ratings_as_of, load_canonical_results
from common.team_sheet import spine_disruption_adjustment
from common.weather import margin_stdev_multiplier_for

logger = logging.getLogger(__name__)

_N_SIMULATIONS = 10000


def run_stats_variant_for_round(
    variant_id: str,
    match_ids: list[str],
    round_number: int,
    season: int,
    sim_table=None,
    results_table=None,
    teams_table=None,
    injuries_table=None,
    weather_table=None,
) -> list[dict]:
    """Predict every match in `match_ids` using ratings as they stood before
    `round_number` (no look-ahead). Returns the simulation prediction records
    written (or that would be written) to `sim_table`.

    `teams_table`/`injuries_table`/`weather_table` are optional
    (docs/plans/11-team-sheet-injury-weather-signals.md, Phases 2-4) — see
    `v1/orchestrator/stats_predictor.py::predict_round` for the same lookups
    on the main path; omitted, or no matching row, both fail open to no
    adjustment. Unlike the main path (which has full `Match` objects), the
    weather lookup here needs `teams_table` too — it recovers venue/kickoff
    date from the `{matchId}#home` draw-entry row the orchestrator writes for
    every match (`v1/orchestrator/lambda_handler.py` step 2), since this
    runner only has bare matchId strings.
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

        generated_at = datetime.now(UTC).isoformat()
        home_adjustment = away_adjustment = 0.0
        if teams_table is not None:
            team_sheet_item = teams_table.get_item(
                Key={"teamId": match_id, "round": str(round_number)}
            ).get("Item") or {}
            home_adjustment = spine_disruption_adjustment(team_sheet_item.get("spine_changed_home", False))
            away_adjustment = spine_disruption_adjustment(team_sheet_item.get("spine_changed_away", False))

            if injuries_table is not None:
                sheet = {
                    "homePlayers": team_sheet_item.get("homePlayers", []),
                    "awayPlayers": team_sheet_item.get("awayPlayers", []),
                }
                home_adjustment += injury_adjustment(
                    has_spine_player_ruled_out(sheet, "homePlayers", home, injuries_table, before=generated_at)
                )
                away_adjustment += injury_adjustment(
                    has_spine_player_ruled_out(sheet, "awayPlayers", away, injuries_table, before=generated_at)
                )

        margin_multiplier = 1.0
        if teams_table is not None and weather_table is not None:
            draw_entry = teams_table.get_item(
                Key={"teamId": f"{match_id}#home", "round": str(round_number)}
            ).get("Item") or {}
            venue = draw_entry.get("venue")
            kickoff_date = draw_entry["kickOff"][:10] if draw_entry.get("kickOff") else None
            if venue:
                margin_multiplier = margin_stdev_multiplier_for(weather_table, venue, kickoff_date)

        rng = random.Random(f"{variant_id}:{match_id}")
        pred = predict_match(
            home, away, ratings, DEFAULT_HOME_ADVANTAGE, _N_SIMULATIONS, rng,
            home_rating_adjustment=home_adjustment,
            away_rating_adjustment=away_adjustment,
            margin_stdev_multiplier=margin_multiplier,
        )

        record = {
            "pk": f"{match_id}#{variant_id}",
            "matchId": match_id,
            "variantId": variant_id,
            "roundNumber": round_number,
            "season": season,
            "generatedAt": generated_at,
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
