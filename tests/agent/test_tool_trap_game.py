"""Tests for detect_trap_game against the REAL data shapes:
- teams table draw/team-sheet rows: one row per match (teamId=matchId,
  round=str(round_number)), homeTeam/awayTeam stored as nickname casing.
- teams table ladder row (teamId=f"ladder#{season}", round="current"):
  positions[].team_name stored as canonical slugs.
- results table: homeTeam/awayTeam/winner stored as canonical slugs
  (scrapers/nrl/results.py applies to_slug() at scrape time).

Confirmed against production data on 2026-07-26 — the ladder previously used
"team" (not "team_name") as the key here, and the draw-lookup helpers assumed
a per-side-row schema that has never matched the real teams table, so
sandwich_game detection silently never fired and the ladder lookup raised a
hard KeyError. See v1/agent/tools/trap_game.py's module docstring."""
import boto3
import pytest
from moto import mock_aws

from v1.agent.tools.trap_game import detect_trap_game

TEAMS_TABLE = "teams"
RESULTS_TABLE = "results"


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

        # Ladder positions store canonical slugs in team_name, as scraped for real.
        teams_tbl.put_item(Item={
            "teamId": "ladder#2026",
            "round": "current",
            "positions": [
                {"team_name": "storm", "position": 1},
                {"team_name": "panthers", "position": 2},
                {"team_name": "roosters", "position": 3},
                {"team_name": "broncos", "position": 4},
                {"team_name": "sharks", "position": 5},
                {"team_name": "cowboys", "position": 6},
                {"team_name": "bulldogs", "position": 7},
                {"team_name": "sea-eagles", "position": 8},
                {"team_name": "rabbitohs", "position": 9},
                {"team_name": "eels", "position": 10},
                {"team_name": "dragons", "position": 11},
                {"team_name": "knights", "position": 12},
                {"team_name": "raiders", "position": 13},
                {"team_name": "warriors", "position": 14},
                {"team_name": "titans", "position": 15},
                {"team_name": "dolphins", "position": 16},
                {"team_name": "wests-tigers", "position": 17},
            ],
            "scraped_at": "2026-06-01T00:00:00Z",
        })

        yield {"teams": teams_tbl, "results": results_tbl}


def _seed_draw_entry(teams_tbl, match_id, round_num, home, away, kick_off="2026-06-07T09:50:00Z"):
    """Seed a single real-shaped draw/team-sheet row — homeTeam/awayTeam in
    nickname casing, exactly as scrapers.nrl.team_sheet writes it."""
    teams_tbl.put_item(Item={
        "teamId": match_id,
        "round": str(round_num),
        "homeTeam": home,
        "awayTeam": away,
        "homePlayers": [],
        "awayPlayers": [],
        "matchState": "Pre",
        "kickOff": kick_off,
        "scraped_at": "2026-06-01T00:00:00Z",
    })


def _seed_result(results_tbl, match_id, home_slug, away_slug, home_score, away_score, winner_slug, date="2026-06-01"):
    """Seed a result row with slugged team names, matching
    scrapers/nrl/results.py's real to_slug()-at-write-time behaviour."""
    results_tbl.put_item(Item={
        "matchId": match_id,
        "scoredAt": f"{date}T10:00:00Z",
        "homeTeam": home_slug,
        "awayTeam": away_slug,
        "homeScore": home_score,
        "awayScore": away_score,
        "winner": winner_slug,
        "margin": abs(home_score - away_score),
        "matchState": "FullTime",
    })


def test_sandwich_game(tables):
    """Panthers (2nd) play Knights (12th) in R15, between Storm (1st) in R14 and Roosters (3rd) in R16."""
    t, r = tables["teams"], tables["results"]

    # R14: Panthers vs Storm
    _seed_draw_entry(t, "round-14-panthers-v-storm", 14, "Panthers", "Storm",
                     kick_off="2026-05-31T09:50:00Z")
    _seed_result(r, "round-14-panthers-v-storm", "panthers", "storm", 22, 20, "panthers", "2026-05-31")

    # R15: Panthers vs Knights (the match under analysis) — nickname casing,
    # exercising the slug-normalisation fix against a mismatched-case input.
    _seed_draw_entry(t, "round-15-panthers-v-knights", 15, "Panthers", "Knights",
                     kick_off="2026-06-07T09:50:00Z")

    # R16: Panthers vs Roosters
    _seed_draw_entry(t, "round-16-roosters-v-panthers", 16, "Roosters", "Panthers",
                     kick_off="2026-06-14T09:50:00Z")

    result = detect_trap_game(
        match_id="round-15-panthers-v-knights",
        round_number=15,
        season=2026,
        home_team="Panthers",
        away_team="Knights",
        teams_table=t,
        results_table=r,
    )

    indicator_types = [i["type"] for i in result["indicators"]]
    assert "sandwich_game" in indicator_types
    assert result["trap_score"] >= 1.5
    assert result["favourite"] == "panthers"
    assert result["underdog"] == "knights"


def test_emotional_letdown(tables):
    """Team won previous game by 20+ points — letdown risk."""
    t, r = tables["teams"], tables["results"]

    # R14: Panthers thrashed Dolphins 40-10
    _seed_draw_entry(t, "round-14-panthers-v-dolphins", 14, "Panthers", "Dolphins",
                     kick_off="2026-05-31T09:50:00Z")
    _seed_result(r, "round-14-panthers-v-dolphins", "panthers", "dolphins", 40, 10, "panthers", "2026-05-31")

    # R15: Panthers vs Knights
    _seed_draw_entry(t, "round-15-panthers-v-knights", 15, "Panthers", "Knights",
                     kick_off="2026-06-07T09:50:00Z")

    result = detect_trap_game(
        match_id="round-15-panthers-v-knights",
        round_number=15,
        season=2026,
        home_team="Panthers",
        away_team="Knights",
        teams_table=t,
        results_table=r,
    )

    indicator_types = [i["type"] for i in result["indicators"]]
    assert "emotional_letdown" in indicator_types


def test_revenge_game(tables):
    """Underdog lost close game earlier this season — revenge factor."""
    t, r = tables["teams"], tables["results"]

    # Earlier meeting R5: Panthers beat Knights 18-14 (margin 4 < 8)
    _seed_result(r, "round-5-panthers-v-knights", "panthers", "knights", 18, 14, "panthers", "2026-04-05")

    # R15: Panthers vs Knights
    _seed_draw_entry(t, "round-15-panthers-v-knights", 15, "Panthers", "Knights",
                     kick_off="2026-06-07T09:50:00Z")

    result = detect_trap_game(
        match_id="round-15-panthers-v-knights",
        round_number=15,
        season=2026,
        home_team="Panthers",
        away_team="Knights",
        teams_table=t,
        results_table=r,
    )

    indicator_types = [i["type"] for i in result["indicators"]]
    assert "revenge_game" in indicator_types


def test_dead_rubber(tables):
    """Favourite clinched top-4, underdog fighting for 8th."""
    t, r = tables["teams"], tables["results"]

    # Bulldogs are 7th (fighting for 8th), Panthers are 2nd (clinched top-4)
    _seed_draw_entry(t, "round-22-panthers-v-bulldogs", 22, "Panthers", "Bulldogs",
                     kick_off="2026-08-08T09:50:00Z")

    result = detect_trap_game(
        match_id="round-22-panthers-v-bulldogs",
        round_number=22,
        season=2026,
        home_team="Panthers",
        away_team="Bulldogs",
        teams_table=t,
        results_table=r,
    )

    indicator_types = [i["type"] for i in result["indicators"]]
    assert "dead_rubber" in indicator_types


def test_no_trap_indicators(tables):
    """Normal match with no trap indicators should return is_trap_game=False."""
    t, r = tables["teams"], tables["results"]

    # R15: Storm vs Roosters — top teams playing each other, no trap
    _seed_draw_entry(t, "round-15-storm-v-roosters", 15, "Storm", "Roosters",
                     kick_off="2026-06-07T09:50:00Z")

    result = detect_trap_game(
        match_id="round-15-storm-v-roosters",
        round_number=15,
        season=2026,
        home_team="Storm",
        away_team="Roosters",
        teams_table=t,
        results_table=r,
    )

    assert result["is_trap_game"] is False
    assert result["trap_score"] == 0
    assert result["indicators"] == []


def test_round_1_no_previous(tables):
    """Round 1 has no previous game — should handle gracefully."""
    t, r = tables["teams"], tables["results"]

    _seed_draw_entry(t, "round-1-panthers-v-knights", 1, "Panthers", "Knights",
                     kick_off="2026-03-07T09:50:00Z")
    # R2 fixture
    _seed_draw_entry(t, "round-2-storm-v-panthers", 2, "Storm", "Panthers",
                     kick_off="2026-03-14T09:50:00Z")

    result = detect_trap_game(
        match_id="round-1-panthers-v-knights",
        round_number=1,
        season=2026,
        home_team="Panthers",
        away_team="Knights",
        teams_table=t,
        results_table=r,
    )

    # Should not crash, sandwich_game shouldn't fire without previous game
    indicator_types = [i["type"] for i in result["indicators"]]
    assert "sandwich_game" not in indicator_types


def test_composite_score(tables):
    """Multiple indicators should sum correctly."""
    t, r = tables["teams"], tables["results"]

    # R14: Panthers beat Storm by 30 (emotional letdown: +1.0)
    _seed_draw_entry(t, "round-14-panthers-v-storm", 14, "Panthers", "Storm",
                     kick_off="2026-05-31T09:50:00Z")
    _seed_result(r, "round-14-panthers-v-storm", "panthers", "storm", 40, 10, "panthers", "2026-05-31")

    # R15: Panthers vs Knights (the match)
    _seed_draw_entry(t, "round-15-panthers-v-knights", 15, "Panthers", "Knights",
                     kick_off="2026-06-07T09:50:00Z")

    # R16: Panthers vs Roosters (sandwich: +1.5)
    _seed_draw_entry(t, "round-16-roosters-v-panthers", 16, "Roosters", "Panthers",
                     kick_off="2026-06-14T09:50:00Z")

    # Earlier close loss by Knights (revenge: +0.5)
    _seed_result(r, "round-5-panthers-v-knights", "panthers", "knights", 18, 14, "panthers", "2026-04-05")

    result = detect_trap_game(
        match_id="round-15-panthers-v-knights",
        round_number=15,
        season=2026,
        home_team="Panthers",
        away_team="Knights",
        teams_table=t,
        results_table=r,
    )

    assert result["is_trap_game"] is True
    # sandwich(1.5) + emotional_letdown(1.0) + revenge(0.5) = 3.0
    assert result["trap_score"] >= 2.5
    assert len(result["indicators"]) >= 3


def test_ladder_lookup_matches_real_data_shape(tables):
    """Regression test for the confirmed production bug: ladder positions are
    keyed by "team_name" (not "team"), and detect_trap_game must not raise."""
    t, r = tables["teams"], tables["results"]
    _seed_draw_entry(t, "round-15-panthers-v-knights", 15, "Panthers", "Knights")

    result = detect_trap_game(
        match_id="round-15-panthers-v-knights",
        round_number=15,
        season=2026,
        home_team="Panthers",
        away_team="Knights",
        teams_table=t,
        results_table=r,
    )

    # Panthers (2nd) vs Knights (unranked -> default 17th) — Panthers favourite
    assert result["favourite"] == "panthers"
    assert result["underdog"] == "knights"


def test_home_team_slug_input_matches_nickname_cased_draw_rows(tables):
    """A caller passing an already-slugged team name (as some agent tool
    calls do) must still match nickname-cased homeTeam/awayTeam draw rows."""
    t, r = tables["teams"], tables["results"]
    _seed_draw_entry(t, "round-14-panthers-v-storm", 14, "Panthers", "Storm",
                     kick_off="2026-05-31T09:50:00Z")
    _seed_draw_entry(t, "round-15-panthers-v-knights", 15, "Panthers", "Knights",
                     kick_off="2026-06-07T09:50:00Z")
    _seed_draw_entry(t, "round-16-roosters-v-panthers", 16, "Roosters", "Panthers",
                     kick_off="2026-06-14T09:50:00Z")

    result = detect_trap_game(
        match_id="round-15-panthers-v-knights",
        round_number=15,
        season=2026,
        home_team="panthers",  # already slugged, unlike the other tests
        away_team="knights",
        teams_table=t,
        results_table=r,
    )

    indicator_types = [i["type"] for i in result["indicators"]]
    assert "sandwich_game" in indicator_types
