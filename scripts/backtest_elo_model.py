#!/usr/bin/env python3
"""
Offline backtest of the Elo + Monte Carlo predictor against real 2026 results.
See docs/plans/10-elo-monte-carlo-predictor.md (Phase 1).

Walks the `results` table chronologically by round. For each match, predicts
using team ratings as they stood *before* that round (no look-ahead — all
matches in a round are predicted off the same pre-round ratings, then all of
that round's results are applied before moving to the next round). Reports
pick_rate / mean_margin_error / Brier score in the same units as
scoring/scorer.py, for both the full model (with home advantage) and a
no-home-advantage baseline.

Scope: only round-qualified matchIds are used (see the Phase 1 [SPIKE] note
in the plan doc) — legacy unqualified matchIds from before the identity
migration can silently collide and are excluded.

Uses the same common.stats_model.ratings/confidence modules as the live
tournament stats variant (v1/tournament/stats_variant_runner.py) — this
script exists to validate that shared core, not a separate implementation.

Usage:
    AWS_DEFAULT_REGION=ap-southeast-2 python3 scripts/backtest_elo_model.py
    AWS_DEFAULT_REGION=ap-southeast-2 python3 scripts/backtest_elo_model.py --n-simulations 20000 --seed 7
"""
from __future__ import annotations

import argparse
import random
from collections import defaultdict
from dataclasses import dataclass

import boto3

from common.match_id import round_of
from common.stats_model.confidence import confidence_for
from common.stats_model.elo import DEFAULT_HOME_ADVANTAGE
from common.stats_model.ratings import compute_ratings_as_of, load_canonical_results
from common.stats_model.simulate import simulate_match
from common.teams import to_slug

RESULTS_TABLE = "results"

# Same mapping scoring/scorer.py uses, kept in sync so Brier scores here are
# directly comparable to the LLM's scored predictions.
_CONFIDENCE_PROB = {"HIGH": 0.85, "MEDIUM": 0.65, "LOW": 0.55}


@dataclass
class BacktestRow:
    match_id: str
    round_number: int
    correct_pick: bool
    margin_error: int
    confidence: str


def run_backtest(
    results: list[dict], home_advantage: float, n_simulations: int, seed: int
) -> list[BacktestRow]:
    rows_by_round: dict[int, list[dict]] = defaultdict(list)
    for row in results:
        # round_of() is Optional in general, but load_canonical_results() already
        # filtered to round-qualified matchIds, so this is always an int here.
        round_number = round_of(row["matchId"])
        assert round_number is not None
        rows_by_round[round_number].append(row)

    backtest_rows: list[BacktestRow] = []
    for round_number in sorted(rows_by_round):
        ratings = compute_ratings_as_of(results, round_number, home_advantage)
        for row in rows_by_round[round_number]:
            home, away = to_slug(row["homeTeam"]), to_slug(row["awayTeam"])
            rng = random.Random(f"{seed}:{row['matchId']}")
            sim = simulate_match(
                ratings[home], ratings[away], home_advantage, n_simulations, rng
            )
            predicted_winner = home if sim.home_win_probability >= 0.5 else away
            predicted_margin = round(abs(sim.expected_margin))
            confidence = confidence_for(sim.home_win_probability)

            actual_winner = to_slug(row["winner"])
            actual_margin = int(row["margin"])
            backtest_rows.append(BacktestRow(
                match_id=row["matchId"],
                round_number=round_number,
                correct_pick=predicted_winner == actual_winner,
                margin_error=abs(predicted_margin - actual_margin),
                confidence=confidence,
            ))

    return backtest_rows


def summarize(label: str, rows: list[BacktestRow]) -> None:
    total = len(rows)
    correct = sum(1 for r in rows if r.correct_pick)
    pick_rate = correct / total
    mean_margin_error = sum(r.margin_error for r in rows) / total
    brier = sum(
        (_CONFIDENCE_PROB[r.confidence] - (1 if r.correct_pick else 0)) ** 2 for r in rows
    ) / total

    print(f"\n=== {label} ({total} matches) ===")
    print(f"pick_rate:         {pick_rate:.4f} ({correct}/{total})")
    print(f"mean_margin_error: {mean_margin_error:.2f}")
    print(f"brier_score:       {brier:.4f}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n-simulations", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    results_table = boto3.resource("dynamodb").Table(RESULTS_TABLE)
    results = load_canonical_results(results_table)
    if not results:
        print("No round-qualified results found — nothing to backtest.")
        return
    rounds = sorted({r for r in (round_of(row["matchId"]) for row in results) if r is not None})
    print(f"Backtest window: rounds {rounds[0]}-{rounds[-1]} ({len(results)} matches)")
    print(f"All teams start at rating 1500.0 — round-{rounds[0]} form is not captured,")
    print("since reliable per-team history doesn't exist before this window.")

    with_advantage = run_backtest(results, DEFAULT_HOME_ADVANTAGE, args.n_simulations, args.seed)
    summarize(f"Elo + Monte Carlo (home_advantage={DEFAULT_HOME_ADVANTAGE})", with_advantage)

    no_advantage = run_backtest(results, 0.0, args.n_simulations, args.seed)
    summarize("Baseline: no home advantage", no_advantage)


if __name__ == "__main__":
    main()
