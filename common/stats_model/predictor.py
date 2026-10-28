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
from common.stats_model.sport import NRL, SportModel

N_SIMULATIONS = 10000


@dataclass
class StatsPrediction:
    predicted_winner: str
    predicted_margin: int
    margin_low: int
    margin_high: int
    confidence: str
    key_factors: list[str]
    reasoning: str
    home_win_probability: float


def _round_to_even(x: float) -> int:
    """Snap to the nearest even number. NRL margins are even-biased (tries,
    conversions and penalties are all even-valued), so a range like `4-18`
    reads more naturally than `3-17` and doesn't imply a lone field goal
    decided the game."""
    return int(2 * round(x / 2))


def _snap(x: float, step: int) -> int:
    """Snap to the nearest multiple of `SportModel.margin_step` — 2 is exactly
    `_round_to_even` above (NRL), 1 is plain integers."""
    return int(step * round(x / step))


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
    *,
    model: SportModel = NRL,
    neutral: bool = False,
) -> StatsPrediction:
    """`home_rating_adjustment`/`away_rating_adjustment`/`margin_stdev_multiplier`
    are Phase 1 plumbing for docs/plans/11-team-sheet-injury-weather-signals.md —
    optional, additive nudges to the *effective* rating fed into the simulation,
    never to the persisted Elo history. All default to inert so every existing
    call site is unaffected until a later phase wires a real signal through them.

    `model` supplies the sport's margin fit, confidence thresholds, margin-band
    snapping and home-advantage wording; defaults to NRL (common/stats_model/sport.py).

    `neutral=True` (a neutral-site game) simulates with zero home advantage,
    whatever `home_advantage` says, and words key_factors/reasoning accordingly.
    """
    if neutral:
        home_advantage = 0.0
    home_rating, away_rating = ratings[home], ratings[away]
    home_effective = home_rating + home_rating_adjustment
    away_effective = away_rating + away_rating_adjustment
    sim = simulate_match(
        home_effective, away_effective, home_advantage, n_simulations, rng,
        margin_stdev_multiplier=margin_stdev_multiplier, model=model,
    )
    predicted_winner = home if sim.home_win_probability >= 0.5 else away
    predicted_margin = round(abs(sim.expected_margin))
    # Honest margin band rather than a single false-precision number: one
    # standard deviation either side of the mean *winning* margin (the margin
    # conditioned on the predicted side winning, so it isn't regressed toward
    # zero by the upset trials the way `predicted_margin` is), snapped to the
    # sport's margin step (even numbers for NRL), low clamped at 0. The band
    # shifts with the matchup — a bigger rating gap lifts both ends — while
    # staying ~2 SD wide.
    margin_low = _snap(max(sim.winning_margin_mean - sim.margin_stdev, 0.0), model.margin_step)
    margin_high = _snap(sim.winning_margin_mean + sim.margin_stdev, model.margin_step)
    confidence = confidence_for(sim.home_win_probability, model=model)
    elo_diff = home_rating - away_rating
    # Human-readable text only: predicted_winner and ids stay slugs.
    home_name, away_name = model.team_label(home), model.team_label(away)
    winner_name = model.team_label(predicted_winner)

    def signed(x: float) -> str:
        return f"{round(x):+d}" if model.signed_int_text else f"{x:+.0f}"

    key_factors = [
        f"Elo rating gap: {home_name} {home_rating:.0f} vs {away_name} {away_rating:.0f} ({signed(elo_diff)})",
        "Neutral site: no home advantage applied" if neutral
        else f"{model.home_label} advantage (+{home_advantage:.0f} Elo) applied to {home_name}",
        f"Simulated home win probability {sim.home_win_probability:.1%} over "
        f"{n_simulations:,} Monte Carlo trials",
    ]
    if home_rating_adjustment:
        key_factors.append(
            f"{home_name} rating adjusted {signed(home_rating_adjustment)} ahead of kickoff "
            "(team sheet/injury signal)"
        )
    if away_rating_adjustment:
        key_factors.append(
            f"{away_name} rating adjusted {signed(away_rating_adjustment)} ahead of kickoff "
            "(team sheet/injury signal)"
        )
    if margin_stdev_multiplier != 1.0:
        key_factors.append(
            f"Match-day variance widened {margin_stdev_multiplier:.2f}x (weather signal)"
        )

    # NRL's "Home ground" renders as "home-ground", byte-identical to the original text.
    home_phrase = model.home_label.lower().replace(" ", "-")
    venue = (
        "at a neutral site (no home advantage)" if neutral
        else f"before {home_phrase} adjustment (+{home_advantage:.0f} to {home_name})"
    )
    reasoning = (
        f"Elo + Monte Carlo model (no LLM). {home_name} rated {home_rating:.0f}, {away_name} rated "
        f"{away_rating:.0f} {venue}. "
        f"{n_simulations:,} simulated trials gave {home_name} a {sim.home_win_probability:.1%} win "
        f"probability, picking {winner_name} by {margin_low}-{margin_high} "
        f"(point estimate {predicted_margin}, +/-1 SD of the simulated margin, {confidence} confidence). "
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
        margin_low=margin_low,
        margin_high=margin_high,
        confidence=confidence,
        key_factors=key_factors,
        reasoning=reasoning[:2000],
        home_win_probability=sim.home_win_probability,
    )
