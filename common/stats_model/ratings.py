"""Team rating history shared by the offline backtest (scripts/backtest_elo_model.py)
and the live tournament stats variant (v1/tournament/stats_variant_runner.py). See
docs/plans/10-elo-monte-carlo-predictor.md.

Ratings are recomputed from `results` on every call rather than persisted — at the
current data scale (a season is a few hundred matches) a full walk-forward replay is
effectively instant, and it keeps the model stateless: no rating-update hook to wire
into the scoring Lambda, no risk of ratings drifting out of sync with `results`.
Revisit only if this ever shows up as a real cost/latency problem.
"""
from __future__ import annotations

from collections import defaultdict

from common.dynamo import scan_all
from common.match_id import is_canonical, round_of
from common.stats_model.elo import update_ratings
from common.teams import to_slug

STARTING_RATING = 1500.0


def load_canonical_results(results_table) -> list[dict]:
    """One row per round-qualified matchId (latest scoredAt wins), sorted by round.

    Legacy unqualified matchIds (pre round-qualification migration) are excluded —
    they can silently collide if the same two teams played twice in a season. See
    the Phase 1 [SPIKE] note in docs/plans/10-elo-monte-carlo-predictor.md.
    """
    rows = scan_all(results_table)
    latest: dict[str, dict] = {}
    for row in rows:
        match_id = row["matchId"]
        if not is_canonical(match_id):
            continue
        if match_id not in latest or row["scoredAt"] > latest[match_id]["scoredAt"]:
            latest[match_id] = row
    return sorted(latest.values(), key=lambda r: (round_of(r["matchId"]), r["matchId"]))


def compute_ratings_as_of(
    results: list[dict], before_round: int, home_advantage: float
) -> defaultdict[str, float]:
    """Team ratings after replaying every result strictly before `before_round`.

    No look-ahead: a match in `before_round` itself (or later) never affects the
    returned ratings — this is what predicting off "ratings as they stood before
    this round" means.
    """
    ratings: defaultdict[str, float] = defaultdict(lambda: STARTING_RATING)
    for row in results:
        round_number = round_of(row["matchId"])
        if round_number is None or round_number >= before_round:
            continue
        home, away = to_slug(row["homeTeam"]), to_slug(row["awayTeam"])
        home_new, away_new = update_ratings(
            ratings[home], ratings[away],
            int(row["homeScore"]), int(row["awayScore"]),
            home_advantage=home_advantage,
        )
        ratings[home], ratings[away] = home_new, away_new
    return ratings
