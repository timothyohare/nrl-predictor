"""Shared Elo + Monte Carlo prediction adapter. See docs/plans/10-elo-monte-carlo-predictor.md.

Both the main predictions path (v1/orchestrator/stats_predictor.py, Phase 3 cutover)
and the prompt-tournament variant (v1/tournament/stats_variant_runner.py, Phase 2)
call `predict_match()` so the two never compute a prediction two different ways.
Deliberately does not import v1.agent.graph or take betting-market data as input —
same "no LLM, no odds" invariants as the tournament variant.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from common.stats_model.confidence import confidence_for
from common.stats_model.simulate import simulate_match

N_SIMULATIONS = 10000


@dataclass
class StatsPrediction:
    predicted_winner: str
    predicted_margin: int
    confidence: str
    key_factors: list[str]
    reasoning: str
    home_win_probability: float


def predict_match(
    home: str,
    away: str,
    ratings: dict[str, float],
    home_advantage: float,
    n_simulations: int,
    rng: random.Random,
    home_rating_adjustment: float = 0.0,
    away_rating_adjustment: float = 0.0,
    margin_stdev_multiplier: float = 1.0,
) -> StatsPrediction:
    """`home_rating_adjustment`/`away_rating_adjustment`/`margin_stdev_multiplier`
    are Phase 1 plumbing for docs/plans/11-team-sheet-injury-weather-signals.md —
    optional, additive nudges to the *effective* rating fed into the simulation,
    never to the persisted Elo history. All default to inert so every existing
    call site is unaffected until a later phase wires a real signal through them.
    """
    home_rating, away_rating = ratings[home], ratings[away]
    home_effective = home_rating + home_rating_adjustment
    away_effective = away_rating + away_rating_adjustment
    sim = simulate_match(
        home_effective, away_effective, home_advantage, n_simulations, rng,
        margin_stdev_multiplier=margin_stdev_multiplier,
    )
    predicted_winner = home if sim.home_win_probability >= 0.5 else away
    predicted_margin = round(abs(sim.expected_margin))
    confidence = confidence_for(sim.home_win_probability)
    elo_diff = home_rating - away_rating

    key_factors = [
        f"Elo rating gap: {home} {home_rating:.0f} vs {away} {away_rating:.0f} ({elo_diff:+.0f})",
        f"Home ground advantage (+{home_advantage:.0f} Elo) applied to {home}",
        f"Simulated home win probability {sim.home_win_probability:.1%} over "
        f"{n_simulations:,} Monte Carlo trials",
    ]
    if home_rating_adjustment:
        key_factors.append(
            f"{home} rating adjusted {home_rating_adjustment:+.0f} ahead of kickoff "
            "(team sheet/injury signal)"
        )
    if away_rating_adjustment:
        key_factors.append(
            f"{away} rating adjusted {away_rating_adjustment:+.0f} ahead of kickoff "
            "(team sheet/injury signal)"
        )
    if margin_stdev_multiplier != 1.0:
        key_factors.append(
            f"Match-day variance widened {margin_stdev_multiplier:.2f}x (weather signal)"
        )

    reasoning = (
        f"Elo + Monte Carlo model (no LLM). {home} rated {home_rating:.0f}, {away} rated "
        f"{away_rating:.0f} before home-ground adjustment (+{home_advantage:.0f} to {home}). "
        f"{n_simulations:,} simulated trials gave {home} a {sim.home_win_probability:.1%} win "
        f"probability, picking {predicted_winner} by {predicted_margin} ({confidence} confidence). "
    )
    if home_rating_adjustment or away_rating_adjustment or margin_stdev_multiplier != 1.0:
        reasoning += (
            "Pre-match signal adjustments applied ahead of simulation — see key_factors "
            "for team sheet/injury/weather detail."
        )
    else:
        reasoning += (
            "No team-sheet, injury, weather, or narrative signal used — "
            "see docs/plans/10-elo-monte-carlo-predictor.md."
        )

    return StatsPrediction(
        predicted_winner=predicted_winner,
        predicted_margin=predicted_margin,
        confidence=confidence,
        key_factors=key_factors,
        reasoning=reasoning[:2000],
        home_win_probability=sim.home_win_probability,
    )
