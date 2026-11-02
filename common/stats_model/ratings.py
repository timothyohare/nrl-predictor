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
from collections.abc import Iterable
from typing import Protocol

from common.dynamo import scan_all
from common.match_id import is_canonical, round_of
from common.stats_model.elo import update_ratings
from common.stats_model.sport import NRL, SportModel
from common.teams import to_slug

# Alias of the NRL SportModel, kept for existing call sites.
STARTING_RATING = NRL.starting_rating


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


class ReplayGame(Protocol):
    """What `replay_ratings` needs from a game. Team names must already be
    slugged; `None` scores mean the game hasn't been played yet."""

    @property
    def home(self) -> str: ...
    @property
    def away(self) -> str: ...
    @property
    def home_score(self) -> int | None: ...
    @property
    def away_score(self) -> int | None: ...
    @property
    def season(self) -> int: ...
    @property
    def week(self) -> int: ...
    @property
    def neutral(self) -> bool: ...


def regress_ratings(ratings: dict[str, float], model: SportModel, seasons: int = 1) -> None:
    """Move every rating `model.season_regression` of the way back to
    `model.starting_rating`, once per season boundary crossed (in place)."""
    keep = (1.0 - model.season_regression) ** seasons
    for team, rating in ratings.items():
        ratings[team] = model.starting_rating + (rating - model.starting_rating) * keep


def replay_ratings(
    games: Iterable[ReplayGame],
    model: SportModel,
    before: tuple[int, int] | None = None,
) -> defaultdict[str, float]:
    """Sport-generic counterpart of `compute_ratings_as_of`: team ratings after
    replaying every played game (in `(season, week, home, away)` order) strictly
    before `before`. See the NFL predictor spec (.claude/sdlc/nfl-predictor/spec.md).

    - No look-ahead: a game at or after `before` never affects the result.
    - Neutral-site games are replayed with zero home advantage.
    - At each season boundary — including the one into `before`'s season, so
      week-1 predictions start from regressed ratings — every rating moves
      `model.season_regression` of the way back to `model.starting_rating`,
      once per season crossed (a 2023 -> 2025 gap regresses twice). With
      `season_regression == 0` no regression arithmetic runs at all.
    - An unscored game never crosses a boundary on its own.
    """
    ratings: defaultdict[str, float] = defaultdict(lambda: model.starting_rating)
    current_season: int | None = None

    def cross_into(season: int) -> None:
        if current_season is not None and season > current_season and model.season_regression:
            regress_ratings(ratings, model, seasons=season - current_season)

    for game in sorted(games, key=lambda g: (g.season, g.week, g.home, g.away)):
        if before is not None and (game.season, game.week) >= before:
            break
        if game.home_score is None or game.away_score is None:
            continue
        cross_into(game.season)
        current_season = game.season
        home_new, away_new = update_ratings(
            ratings[game.home], ratings[game.away], game.home_score, game.away_score,
            home_advantage=0.0 if game.neutral else model.home_advantage,
            model=model,
        )
        ratings[game.home], ratings[game.away] = home_new, away_new
    if before is not None:
        cross_into(before[0])
    return ratings
