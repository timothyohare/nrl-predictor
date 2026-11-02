"""Which NFL games the daily run should predict (spec Phase 3, "Target week rule").

- The current season is the latest season in the data — never a hardcoded year.
- The target week is the lowest week of that season with a game still to kick
  off. Only games with ``kickoff_utc > now`` are ever predicted (hindsight guard,
  per the v2 leakage incident); a target-week game already under way is skipped.
- Every game in an earlier week must be final first, since its result feeds the
  ratings. An unscored earlier game blocks the week — unless it is more than 72h
  past kickoff, when it is treated as cancelled (the 2022 BUF-CIN game was simply
  dropped from nflverse) so it can't block forever. An unscored earlier game with
  no kickoff time also blocks: it can't be aged out, so it's surfaced loudly.
- A target-week game that already kicked off (the first live run landing after
  Thursday night football) is listed in ``started``: the handler gives it a
  labelled backfill, never a live prediction.
- No game left to kick off (season over, or week 18 done before the Wild Card
  rows are published) is a quiet no-op, not an error.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from common.nfl.games import Game

CANCELLED_AFTER = timedelta(hours=72)
_NO_KICKOFF = datetime.max.replace(tzinfo=UTC)  # sorts last


@dataclass(frozen=True)
class TargetWeek:
    season: int | None
    week: int | None
    # Target-week games still to kick off, blocked or not (kickoff, matchId order).
    pending: list[Game] = field(default_factory=list)
    blockers: list[Game] = field(default_factory=list)
    cancelled: list[Game] = field(default_factory=list)
    # Target-week games already kicked off — never live-predicted (hindsight guard).
    started: list[Game] = field(default_factory=list)

    @property
    def to_predict(self) -> list[Game]:
        """The games to predict now: the pending ones, unless an earlier week blocks."""
        return [] if self.blockers else self.pending


def _is_future(game: Game, now: datetime) -> bool:
    return game.kickoff_utc is not None and game.kickoff_utc > now


def _is_cancelled(game: Game, now: datetime) -> bool:
    return game.kickoff_utc is not None and now - game.kickoff_utc > CANCELLED_AFTER


def _order(games: Iterable[Game]) -> list[Game]:
    return sorted(games, key=lambda g: (g.kickoff_utc or _NO_KICKOFF, g.match_id))


def select_target(games: Iterable[Game], now: datetime) -> TargetWeek:
    """Apply the target-week rule to `games` (any seasons) at instant `now`."""
    games = list(games)
    if not games:
        return TargetWeek(season=None, week=None)
    season = max(g.season for g in games)
    current = [g for g in games if g.season == season]

    future_weeks = [g.week for g in current if _is_future(g, now)]
    if not future_weeks:
        return TargetWeek(season=season, week=None)
    week = min(future_weeks)

    earlier_unplayed = [g for g in current if g.week < week and not g.played]
    cancelled = _order(g for g in earlier_unplayed if _is_cancelled(g, now))
    blockers = _order(g for g in earlier_unplayed if not _is_cancelled(g, now))
    pending = _order(g for g in current if g.week == week and _is_future(g, now))
    started = _order(g for g in current if g.week == week and g.kickoff_utc is not None
                     and not _is_future(g, now))
    return TargetWeek(season, week, pending, blockers, cancelled, started)
