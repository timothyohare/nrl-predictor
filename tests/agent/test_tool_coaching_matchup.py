import boto3
import pytest
from moto import mock_aws
from agent.tools.coaching_matchup import get_coaching_matchup

TABLE = "results"


@pytest.fixture
def ddb_table():
    with mock_aws():
        boto3.client("dynamodb", region_name="ap-southeast-2").create_table(
            TableName=TABLE,
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
        tbl = boto3.resource("dynamodb", region_name="ap-southeast-2").Table(TABLE)
        # Panthers (Cleary from 2019) vs Storm (Bellamy from 2003)
        # overlap since 2019
        matches = [
            ("2024-03-10", "Panthers", "Storm", 22, 18, "Panthers"),
            ("2024-06-15", "Storm", "Panthers", 24, 20, "Storm"),
            ("2025-04-20", "Panthers", "Storm", 30, 12, "Panthers"),
            ("2025-08-10", "Storm", "Panthers", 16, 14, "Storm"),
            # Old match before Cleary's tenure — should be excluded
            ("2018-05-01", "Panthers", "Storm", 10, 30, "Storm"),
        ]
        for date, home, away, hs, as_, winner in matches:
            tbl.put_item(Item={
                "matchId": f"{home.lower()}-v-{away.lower()}-{date.replace('-', '')}",
                "scoredAt": f"{date}T10:00:00Z",
                "homeTeam": home,
                "awayTeam": away,
                "homeScore": hs,
                "awayScore": as_,
                "winner": winner,
                "margin": abs(hs - as_),
                "matchState": "FullTime",
            })
        yield tbl


def test_returns_coaching_matchup(ddb_table):
    result = get_coaching_matchup("Panthers", "Storm", table=ddb_table)
    assert result["coach_a"]["name"] == "Ivan Cleary"
    assert result["coach_b"]["name"] == "Craig Bellamy"
    assert result["total_games"] == 4  # excludes 2018 match
    assert result["record"]["a_wins"] == 2
    assert result["record"]["b_wins"] == 2


def test_excludes_pre_tenure_matches(ddb_table):
    result = get_coaching_matchup("Panthers", "Storm", table=ddb_table)
    # 2018 match should be excluded (before Cleary started in 2019)
    assert result["total_games"] == 4


def test_last_3_sorted_by_recency(ddb_table):
    result = get_coaching_matchup("Panthers", "Storm", table=ddb_table)
    assert len(result["last_3"]) == 3
    dates = [m["date"] for m in result["last_3"]]
    assert dates == sorted(dates, reverse=True)


def test_edge_shows_even_record(ddb_table):
    result = get_coaching_matchup("Panthers", "Storm", table=ddb_table)
    assert "Even record" in result["edge"]


def test_unknown_team():
    result = get_coaching_matchup("Panthers", "Nonexistent", table=None)
    assert "error" in result


def test_no_matches_between_teams(ddb_table):
    result = get_coaching_matchup("Panthers", "Dolphins", table=ddb_table)
    # Dolphins coach (Woolf) from 2025, no matches with Panthers in fixture
    assert result["total_games"] == 0
    assert "No previous meetings" in result["edge"]
