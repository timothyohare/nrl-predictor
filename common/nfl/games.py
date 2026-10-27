"""Parse nflverse ``games.csv`` into games and (separately) market data.

The game and its betting lines arrive in the same CSV row, so the separation is
structural: `Game` — the only type the model ever sees — has no market fields,
and spread/moneylines go into a separate `Market` keyed by matchId, for display
and comparison only (same rule as NRL odds; see the spec's non-goals).

Verified data facts this relies on (spec, "Verified data facts"):
- stage comes from ``game_type`` (REG/WC/DIV/CON/SB), never the week number;
- neutral comes from ``location`` — ``stadium`` is unreliable (2025_01_KC_LAC
  was played in Brazil but lists SoFi Stadium);
- ``gameday`` + ``gametime`` are US Eastern local time (DST-aware);
- unplayed games have empty scores.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from common.nfl.match_id import match_id
from common.nfl.teams import to_slug

_EASTERN = ZoneInfo("America/New_York")

REQUIRED_COLUMNS = (
    "game_id", "season", "game_type", "week", "gameday", "gametime",
    "away_team", "away_score", "home_team", "home_score", "location",
    "spread_line", "home_moneyline", "away_moneyline",
)


@dataclass(frozen=True)
class Game:
    game_id: str
    match_id: str
    season: int
    week: int
    stage: str
    home: str
    away: str
    home_score: int | None
    away_score: int | None
    neutral: bool
    kickoff_utc: datetime | None

    @property
    def played(self) -> bool:
        return self.home_score is not None and self.away_score is not None

    @property
    def result(self) -> int | None:
        """Home minus away score, or None if unplayed."""
        if self.home_score is None or self.away_score is None:
            return None
        return self.home_score - self.away_score


@dataclass(frozen=True)
class Market:
    """Betting lines for one game. Comparison/display only — never model input.
    ``spread_line > 0`` means the home team is favoured."""

    match_id: str
    spread_line: float | None
    home_moneyline: int | None
    away_moneyline: int | None


def _int_or_none(value: str) -> int | None:
    return int(value) if value.strip() else None


def _float_or_none(value: str) -> float | None:
    return float(value) if value.strip() else None


def _kickoff_utc(gameday: str, gametime: str) -> datetime | None:
    if not gametime.strip():
        return None
    local = datetime.strptime(f"{gameday} {gametime}", "%Y-%m-%d %H:%M").replace(tzinfo=_EASTERN)
    return local.astimezone(UTC)


def parse_csv(text: str) -> tuple[list[Game], dict[str, Market]]:
    """Every row becomes a `Game`; rows with any market data also get a `Market`.

    Raises ValueError naming any missing required column, before parsing a row.
    """
    reader = csv.DictReader(io.StringIO(text))
    missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
    if missing:
        raise ValueError(f"nflverse games.csv is missing required columns: {', '.join(missing)}")

    games: list[Game] = []
    markets: dict[str, Market] = {}
    for row in reader:
        season, week = int(row["season"]), int(row["week"])
        home, away = to_slug(row["home_team"]), to_slug(row["away_team"])
        game = Game(
            game_id=row["game_id"],
            match_id=match_id(season, week, home, away),
            season=season,
            week=week,
            stage=row["game_type"],
            home=home,
            away=away,
            home_score=_int_or_none(row["home_score"]),
            away_score=_int_or_none(row["away_score"]),
            neutral=row["location"] == "Neutral",
            kickoff_utc=_kickoff_utc(row["gameday"], row["gametime"]),
        )
        games.append(game)
        market = Market(
            match_id=game.match_id,
            spread_line=_float_or_none(row["spread_line"]),
            home_moneyline=_int_or_none(row["home_moneyline"]),
            away_moneyline=_int_or_none(row["away_moneyline"]),
        )
        if (market.spread_line, market.home_moneyline, market.away_moneyline) != (None, None, None):
            markets[game.match_id] = market
    return games, markets
