"""Writes the main `predictions` table using the local Elo + Monte Carlo model —
the Phase 3 cutover from the Claude agent. See docs/plans/10-elo-monte-carlo-predictor.md.

Deliberately does not import v1.agent.graph or call the Anthropic API: the whole
point of the cutover is a prediction path with no external rate limit or credit
dependency. Shares its prediction math with the tournament's `stats-elo-v1` variant
via common.stats_model.predictor, so the two never compute a prediction two
different ways.
"""
import logging
import random
from datetime import UTC, datetime

from common.players import has_spine_player_ruled_out, injury_adjustment
from common.stats_model.elo import DEFAULT_HOME_ADVANTAGE
from common.stats_model.predictor import N_SIMULATIONS, predict_match
from common.stats_model.ratings import compute_ratings_as_of, load_canonical_results
from common.team_sheet import spine_disruption_adjustment
from common.teams import to_slug
from common.weather import margin_stdev_multiplier_for
from scrapers.shared.models import Match

logger = logging.getLogger(__name__)

MODEL_ID = "stats-elo-v1"


def predict_round(
    matches: list[Match],
    round_number: int,
    season: int,
    predictions_table,
    results_table,
    teams_table=None,
    injuries_table=None,
    weather_table=None,
) -> list[str]:
    """Predict every match in `matches` using ratings as they stood before
    `round_number` (no look-ahead). Writes an OK row per match on success, a
    FAILED row (same shape as the old agent path) on a per-match error — one
    bad match must not block the rest of the round. Returns the matchIds
    successfully predicted.

    `teams_table` is optional (docs/plans/11-team-sheet-injury-weather-signals.md,
    Phase 2): when given, looks up each match's `spine_changed_home`/
    `spine_changed_away` flags (written by the orchestrator's team-sheet
    scrape step) and applies a provisional rating penalty to the disrupted
    side. Omitted, or no row found for the match, both fail open to no
    adjustment — a missing signal is never an error.

    `injuries_table` is optional (Phase 3): when given *together with*
    `teams_table` (the injury check needs the current spine lineup to know
    who to look up), adds a further provisional penalty to a side with a
    named spine player currently mentioned as "out"/"doubtful". Same
    fail-open posture as the team-sheet signal.

    `weather_table` is optional (Phase 4): when given, looks up the forecast
    for the match's venue/kickoff date and widens the simulated margin
    variance on a bad-weather match. Missing forecast, missing table, or
    unknown kickoff date all fail open to no widening.
    """
    results = load_canonical_results(results_table)
    ratings = compute_ratings_as_of(results, round_number, DEFAULT_HOME_ADVANTAGE)

    predicted: list[str] = []
    for match in matches:
        generated_at = datetime.now(UTC).isoformat()
        try:
            home, away = to_slug(match.home_team), to_slug(match.away_team)
            rng = random.Random(f"{match.match_id}:{generated_at}")

            home_adjustment = away_adjustment = 0.0
            if teams_table is not None:
                team_sheet_item = teams_table.get_item(
                    Key={"teamId": match.match_id, "round": str(round_number)}
                ).get("Item") or {}
                home_adjustment = spine_disruption_adjustment(
                    team_sheet_item.get("spine_changed_home", False)
                )
                away_adjustment = spine_disruption_adjustment(
                    team_sheet_item.get("spine_changed_away", False)
                )

                if injuries_table is not None:
                    sheet = {
                        "homePlayers": team_sheet_item.get("homePlayers", []),
                        "awayPlayers": team_sheet_item.get("awayPlayers", []),
                    }
                    home_adjustment += injury_adjustment(
                        has_spine_player_ruled_out(
                            sheet, "homePlayers", home, injuries_table, before=generated_at
                        )
                    )
                    away_adjustment += injury_adjustment(
                        has_spine_player_ruled_out(
                            sheet, "awayPlayers", away, injuries_table, before=generated_at
                        )
                    )

            kickoff_date = match.kick_off[:10] if match.kick_off else None
            margin_multiplier = margin_stdev_multiplier_for(weather_table, match.venue, kickoff_date)

            pred = predict_match(
                home, away, ratings, DEFAULT_HOME_ADVANTAGE, N_SIMULATIONS, rng,
                home_rating_adjustment=home_adjustment,
                away_rating_adjustment=away_adjustment,
                margin_stdev_multiplier=margin_multiplier,
            )

            existing = predictions_table.query(
                KeyConditionExpression="matchId = :m",
                FilterExpression="#s = :ok",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":m": match.match_id, ":ok": "OK"},
                Select="COUNT",
            )
            predictions_table.put_item(Item={
                "matchId": match.match_id,
                "generatedAt": generated_at,
                "roundNumber": round_number,
                "season": season,
                "predicted_winner": pred.predicted_winner,
                "predicted_margin": pred.predicted_margin,
                "margin_low": pred.margin_low,
                "margin_high": pred.margin_high,
                "confidence": pred.confidence,
                "key_factors": pred.key_factors,
                "reasoning": pred.reasoning,
                "data_freshness": generated_at,
                "model_used": MODEL_ID,
                "prompt_version": MODEL_ID,
                "generation": existing.get("Count", 0) + 1,
                "staleness_flag": False,
                "status": "OK",
            })
            predicted.append(match.match_id)
            logger.info("Stats prediction written for %s", match.match_id)
        except Exception as e:
            logger.error("Stats prediction failed for %s: %s", match.match_id, e, exc_info=True)
            predictions_table.put_item(Item={
                "matchId": match.match_id,
                "generatedAt": generated_at,
                "status": "FAILED",
                "error": str(e),
            })

    logger.info("Stats predictor: wrote %d/%d predictions for round %d",
                len(predicted), len(matches), round_number)
    return predicted
