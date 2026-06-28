import boto3
import pytest
from moto import mock_aws

from v1.agent.tools.spine_synergy import get_spine_synergy

TEAMS_TABLE = "teams"
RESULTS_TABLE = "results"

SPINE_POSITIONS = {1, 6, 7, 9}


def _make_players(spine_names, team_prefix="P"):
    """Create a player list with spine positions filled by given names.
    spine_names: dict {jersey_number: "LastName"} for positions 1, 6, 7, 9.
    """
    players = []
    for num in range(1, 18):
        if num in spine_names:
            name = spine_names[num]
        else:
            name = f"{team_prefix}{num}"
        players.append({
            "jersey_number": num,
            "first_name": "Test",
            "last_name": name,
            "position": f"Pos{num}",
            "is_starting": num <= 13,
            "player_id": f"pid-{team_prefix}-{num}",
        })
    return players


@pytest.fixture
def tables():
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name="ap-southeast-2")
        ddb.create_table(
            TableName=TEAMS_TABLE,
            KeySchema=[
                {"AttributeName": "teamId", "KeyType": "HASH"},
                {"AttributeName": "round", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "teamId", "AttributeType": "S"},
                {"AttributeName": "round", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        ddb.create_table(
            TableName=RESULTS_TABLE,
            KeySchema=[
                {"AttributeName": "matchId", "KeyType": "HASH"},
                {"AttributeName": "scoredAt", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "matchId", "AttributeType": "S"},
                {"AttributeName": "scoredAt", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        res = boto3.resource("dynamodb", region_name="ap-southeast-2")
        teams_tbl = res.Table(TEAMS_TABLE)
        results_tbl = res.Table(RESULTS_TABLE)
        yield {"teams": teams_tbl, "results": results_tbl}


def _seed_team_sheet(teams_tbl, match_id, round_num, home_team, away_team, home_spine, away_spine):
    """Seed a team sheet entry with specific spine players."""
    teams_tbl.put_item(Item={
        "teamId": match_id,
        "round": str(round_num),
        "homeTeam": home_team,
        "awayTeam": away_team,
        "homePlayers": _make_players(home_spine, "H"),
        "awayPlayers": _make_players(away_spine, "A"),
        "matchState": "FullTime",
        "kickOff": f"2026-04-{10 + round_num}T09:50:00Z",
        "scraped_at": "2026-06-01T00:00:00Z",
    })


def _seed_result(results_tbl, match_id, home, away, home_score, away_score, winner, date):
    results_tbl.put_item(Item={
        "matchId": match_id,
        "scoredAt": f"{date}T10:00:00Z",
        "homeTeam": home,
        "awayTeam": away,
        "homeScore": home_score,
        "awayScore": away_score,
        "winner": winner,
        "margin": abs(home_score - away_score),
        "matchState": "FullTime",
    })


def test_established_spine(tables):
    """Same spine for 8 rounds should be flagged as established."""
    t, r = tables["teams"], tables["results"]
    panthers_spine = {1: "Edwards", 6: "Luai", 7: "Cleary", 9: "Koroisau"}
    dogs_spine = {1: "Tracey", 6: "Burton", 7: "Hutchison", 9: "Mahoney"}

    # Seed 8 historical rounds with same spine
    for rnd in range(1, 9):
        mid = f"round-{rnd}-panthers-v-someone"
        _seed_team_sheet(t, mid, rnd, "Panthers", "Bulldogs", panthers_spine, dogs_spine)
        _seed_result(r, mid, "Panthers", "Bulldogs", 24, 12, "Panthers", f"2026-04-{10 + rnd}")

    # Current match (round 9)
    _seed_team_sheet(t, "round-9-panthers-v-bulldogs", 9, "Panthers", "Bulldogs", panthers_spine, dogs_spine)

    result = get_spine_synergy(
        match_id="round-9-panthers-v-bulldogs",
        round_number=9,
        teams_table=t,
        results_table=r,
    )

    home = result["home_team"]
    assert home["team"] == "Panthers"
    assert home["full_spine_games_together"] == 8
    assert home["is_established"] is True
    assert home["flags"] == []


def test_new_spine_combination_flagged(tables):
    """Spine with <5 games together should be flagged."""
    t, r = tables["teams"], tables["results"]
    original_spine = {1: "Edwards", 6: "Luai", 7: "Cleary", 9: "Koroisau"}
    new_spine = {1: "Edwards", 6: "Luai", 7: "Cleary", 9: "NewHooker"}

    # 6 rounds with original spine
    for rnd in range(1, 7):
        mid = f"round-{rnd}-panthers-v-someone"
        _seed_team_sheet(t, mid, rnd, "Panthers", "Broncos",
                         original_spine, {1: "A1", 6: "A6", 7: "A7", 9: "A9"})
        _seed_result(r, mid, "Panthers", "Broncos", 20, 10, "Panthers", f"2026-04-{10 + rnd}")

    # 2 rounds with new hooker
    for rnd in range(7, 9):
        mid = f"round-{rnd}-panthers-v-someone"
        _seed_team_sheet(t, mid, rnd, "Panthers", "Broncos",
                         new_spine, {1: "A1", 6: "A6", 7: "A7", 9: "A9"})
        _seed_result(r, mid, "Panthers", "Broncos", 18, 16, "Panthers", f"2026-04-{10 + rnd}")

    # Current match round 9 with new hooker
    _seed_team_sheet(t, "round-9-panthers-v-broncos", 9, "Panthers", "Broncos",
                     new_spine, {1: "A1", 6: "A6", 7: "A7", 9: "A9"})

    result = get_spine_synergy(
        match_id="round-9-panthers-v-broncos",
        round_number=9,
        teams_table=t,
        results_table=r,
    )

    home = result["home_team"]
    assert home["full_spine_games_together"] == 2  # only rounds 7-8 with new hooker
    assert home["is_established"] is False
    assert len(home["flags"]) > 0
    assert any("NewHooker" in f or "games together" in f for f in home["flags"])


def test_halves_pairing_tracked(tables):
    """Halves pairing (6+7) should be tracked separately."""
    t, r = tables["teams"], tables["results"]
    spine_v1 = {1: "FB1", 6: "FE1", 7: "HB1", 9: "HK1"}
    spine_v2 = {1: "FB2", 6: "FE1", 7: "HB1", 9: "HK2"}  # same halves, different FB + HK

    for rnd in range(1, 6):
        mid = f"round-{rnd}-storm-v-someone"
        _seed_team_sheet(t, mid, rnd, "Storm", "Raiders", spine_v1,
                         {1: "A1", 6: "A6", 7: "A7", 9: "A9"})
        _seed_result(r, mid, "Storm", "Raiders", 22, 10, "Storm", f"2026-04-{10 + rnd}")

    for rnd in range(6, 9):
        mid = f"round-{rnd}-storm-v-someone"
        _seed_team_sheet(t, mid, rnd, "Storm", "Raiders", spine_v2,
                         {1: "A1", 6: "A6", 7: "A7", 9: "A9"})
        _seed_result(r, mid, "Storm", "Raiders", 20, 14, "Storm", f"2026-04-{10 + rnd}")

    _seed_team_sheet(t, "round-9-storm-v-raiders", 9, "Storm", "Raiders", spine_v2,
                     {1: "A1", 6: "A6", 7: "A7", 9: "A9"})

    result = get_spine_synergy(
        match_id="round-9-storm-v-raiders",
        round_number=9,
        teams_table=t,
        results_table=r,
    )

    home = result["home_team"]
    # Full spine v2 only played together in rounds 6-8 = 3 games
    assert home["full_spine_games_together"] == 3
    # But halves (FE1 + HB1) played together in all 8 rounds
    assert home["halves_games_together"] == 8
    assert home["is_established"] is False  # full spine <5


def test_win_rate_calculation(tables):
    """Win rate should reflect actual results."""
    t, r = tables["teams"], tables["results"]
    spine = {1: "FB", 6: "FE", 7: "HB", 9: "HK"}

    for rnd in range(1, 7):
        mid = f"round-{rnd}-sharks-v-someone"
        _seed_team_sheet(t, mid, rnd, "Sharks", "Eels", spine,
                         {1: "A1", 6: "A6", 7: "A7", 9: "A9"})
        # Win 4, lose 2
        if rnd <= 4:
            _seed_result(r, mid, "Sharks", "Eels", 22, 10, "Sharks", f"2026-04-{10 + rnd}")
        else:
            _seed_result(r, mid, "Sharks", "Eels", 10, 22, "Eels", f"2026-04-{10 + rnd}")

    _seed_team_sheet(t, "round-7-sharks-v-eels", 7, "Sharks", "Eels", spine,
                     {1: "A1", 6: "A6", 7: "A7", 9: "A9"})

    result = get_spine_synergy(
        match_id="round-7-sharks-v-eels",
        round_number=7,
        teams_table=t,
        results_table=r,
    )

    home = result["home_team"]
    assert home["full_spine_games_together"] == 6
    assert abs(home["full_spine_win_rate"] - 4 / 6) < 0.01


def test_no_historical_data(tables):
    """Round 1 with no history should handle gracefully."""
    t, r = tables["teams"], tables["results"]
    spine = {1: "FB", 6: "FE", 7: "HB", 9: "HK"}

    _seed_team_sheet(t, "round-1-cowboys-v-titans", 1, "Cowboys", "Titans", spine,
                     {1: "A1", 6: "A6", 7: "A7", 9: "A9"})

    result = get_spine_synergy(
        match_id="round-1-cowboys-v-titans",
        round_number=1,
        teams_table=t,
        results_table=r,
    )

    home = result["home_team"]
    assert home["full_spine_games_together"] == 0
    assert home["is_established"] is False
