"""nflverse games.csv parsing (common/nfl/games.py) — spec criteria 2.3-2.6."""
from __future__ import annotations

import dataclasses
import re
from datetime import UTC, datetime

import pytest

from common.nfl.games import Game, Market, parse_csv


@pytest.fixture
def parsed(sample_csv_text):
    return parse_csv(sample_csv_text)


@pytest.fixture
def by_id(parsed):
    games, _ = parsed
    return {g.game_id: g for g in games}


def test_every_row_becomes_a_game(parsed, sample_csv_text):
    games, markets = parsed
    assert len(games) == len(sample_csv_text.strip().splitlines()) - 1
    assert all(isinstance(g, Game) for g in games)
    assert set(markets) <= {g.match_id for g in games}
    assert all(isinstance(m, Market) for m in markets.values())


def test_teams_are_slugged_and_match_id_is_canonical(by_id):
    g = by_id["2025_01_KC_LAC"]
    assert (g.home, g.away) == ("chargers", "chiefs")
    assert g.match_id == "nfl-2025-week-1-chargers-v-chiefs"
    sd = by_id["2002_01_SD_CIN"]
    assert (sd.home, sd.away) == ("bengals", "chargers")


def test_playoff_stage_comes_from_game_type(by_id):
    wc_2020 = by_id["2020_18_IND_BUF"]
    assert (wc_2020.season, wc_2020.week, wc_2020.stage) == (2020, 18, "WC")
    assert by_id["2021_19_LV_CIN"].stage == "WC"
    assert by_id["2021_18_KC_DEN"].stage == "REG"
    assert by_id["2020_21_KC_TB"].stage == "SB"


def test_neutral_comes_from_location_not_stadium(parsed, by_id, sample_csv_text):
    assert "SoFi Stadium" in next(
        line for line in sample_csv_text.splitlines() if line.startswith("2025_01_KC_LAC")
    )
    assert by_id["2025_01_KC_LAC"].neutral is True
    assert by_id["2020_21_KC_TB"].neutral is True
    games, _ = parsed
    for line in sample_csv_text.splitlines()[1:]:
        game_id = line.split(",", 1)[0]
        assert by_id[game_id].neutral is (",Neutral," in line)
    assert sum(g.neutral for g in games) == 4


def test_unplayed_game_has_no_scores(by_id):
    g = by_id["2026_08_KC_DEN"]
    assert g.home_score is None and g.away_score is None
    assert g.played is False
    assert g.result is None


def test_tie_is_played(by_id):
    tie = by_id["2002_10_ATL_PIT"]
    assert tie.played is True
    assert (tie.home_score, tie.away_score, tie.result) == (34, 34, 0)


def test_result_is_home_minus_away(by_id):
    assert by_id["2002_01_SD_CIN"].result == -28


@pytest.mark.parametrize(
    ("game_id", "kickoff"),
    [
        ("2025_01_DAL_PHI", datetime(2025, 9, 5, 0, 20, tzinfo=UTC)),  # EDT, crosses midnight UTC
        ("2025_08_GB_PIT", datetime(2025, 10, 27, 0, 20, tzinfo=UTC)),  # last Sunday of EDT
        ("2025_09_KC_BUF", datetime(2025, 11, 2, 21, 25, tzinfo=UTC)),  # first Sunday of EST
        ("2020_18_IND_BUF", datetime(2021, 1, 9, 18, 5, tzinfo=UTC)),  # EST
    ],
)
def test_kickoff_utc_converts_from_us_eastern(by_id, game_id, kickoff):
    assert by_id[game_id].kickoff_utc == kickoff


def test_blank_gametime_gives_no_kickoff(by_id):
    assert by_id["1999_01_BAL_STL"].kickoff_utc is None


def test_game_has_no_market_fields():
    pattern = re.compile(r"spread|moneyline|odds|total_line")
    assert not [f.name for f in dataclasses.fields(Game) if pattern.search(f.name)]


def test_market_carries_spread_and_moneylines(parsed, by_id):
    _, markets = parsed
    m = markets[by_id["2025_01_DAL_PHI"].match_id]
    assert (m.spread_line, m.home_moneyline, m.away_moneyline) == (8.5, -425, 330)
    assert markets[by_id["1999_01_BAL_STL"].match_id].spread_line == 0.0
    assert markets[by_id["1999_01_BAL_STL"].match_id].home_moneyline is None


def test_blank_market_row_is_absent_or_empty(parsed, by_id):
    _, markets = parsed
    m = markets.get(by_id["2026_09_JAX_BAL"].match_id)
    assert m is None or (m.spread_line is None and m.home_moneyline is None)


def test_missing_required_column_fails_loudly(sample_csv_text):
    header, *rest = sample_csv_text.splitlines()
    broken = "\n".join([header.replace("location", "venue_kind"), *rest])
    with pytest.raises(ValueError, match="location"):
        parse_csv(broken)


# --- Phase 2 review follow-ups (folded into Phase 3) ----------------------------

def test_unknown_team_code_fails_loudly(sample_csv_text):
    """N3: live ingest must never invent a 33rd team that starts at 1500."""
    header, first, *rest = sample_csv_text.splitlines()
    cols = header.split(",")
    row = first.split(",")
    row[cols.index("home_team")] = "XYZ"
    with pytest.raises(ValueError, match="XYZ"):
        parse_csv("\n".join([header, ",".join(row), *rest]))


def test_duplicate_match_id_fails_loudly(sample_csv_text):
    """N4: two rows resolving to the same matchId would silently overwrite each other."""
    header, first, *rest = sample_csv_text.splitlines()
    with pytest.raises(ValueError, match="duplicate matchId"):
        parse_csv("\n".join([header, first, *rest, first]))


def test_eastern_zone_is_not_built_at_import():
    """N1: a host with no tz database must still be able to import the module
    (ZoneInfo is resolved lazily, on first kickoff conversion)."""
    from zoneinfo import ZoneInfo

    from common.nfl import games

    assert not [name for name, value in vars(games).items() if isinstance(value, ZoneInfo)]


def test_tzdata_is_a_runtime_dependency():
    """N1: the IANA database ships with the package, not the host image."""
    import tomllib
    from pathlib import Path

    pyproject = Path(__file__).resolve().parents[3] / "pyproject.toml"
    deps = tomllib.loads(pyproject.read_text())["project"]["dependencies"]
    assert any(re.match(r"tzdata\b", d) for d in deps)
