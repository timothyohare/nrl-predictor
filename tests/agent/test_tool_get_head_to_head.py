import boto3
import pytest
from moto import mock_aws

from agent.tools.head_to_head import get_head_to_head

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
        # 3 Sharks wins, 1 Eels win, all at PointsBet Stadium
        for i, (winner, home_score, away_score) in enumerate([
            ("Sharks", 22, 14),
            ("Sharks", 28, 10),
            ("Eels", 18, 12),
            ("Sharks", 20, 16),
        ]):
            home = "Sharks" if i % 2 == 0 else "Eels"
            away = "Eels" if i % 2 == 0 else "Sharks"
            tbl.put_item(Item={
                "matchId": f"sharks-v-eels-{i}",
                "scoredAt": f"2025-0{5+i}-10T10:00:00Z",
                "homeTeam": home,
                "awayTeam": away,
                "homeScore": home_score,
                "awayScore": away_score,
                "winner": winner,
                "margin": abs(home_score - away_score),
                "matchState": "FullTime",
                "venue": "PointsBet Stadium",
            })
        # one match at different venue — should be filterable
        tbl.put_item(Item={
            "matchId": "sharks-v-eels-away",
            "scoredAt": "2025-09-10T10:00:00Z",
            "homeTeam": "Eels",
            "awayTeam": "Sharks",
            "homeScore": 30,
            "awayScore": 6,
            "winner": "Eels",
            "margin": 24,
            "matchState": "FullTime",
            "venue": "CommBank Stadium",
        })
        yield tbl


def test_returns_head_to_head_summary(ddb_table):
    result = get_head_to_head("Sharks", "Eels", venue="PointsBet Stadium", table=ddb_table)
    assert result["team_a_wins"] == 3
    assert result["team_b_wins"] == 1


def test_filters_by_venue(ddb_table):
    result = get_head_to_head("Sharks", "Eels", venue="PointsBet Stadium", table=ddb_table)
    total = result["team_a_wins"] + result["team_b_wins"] + result["draws"]
    assert total == 4


def test_returns_zeros_for_no_history(ddb_table):
    result = get_head_to_head("Panthers", "Storm", venue="BlueBet Stadium", table=ddb_table)
    assert result["team_a_wins"] == 0
    assert result["team_b_wins"] == 0


def test_avg_margin_computed(ddb_table):
    result = get_head_to_head("Sharks", "Eels", venue="PointsBet Stadium", table=ddb_table)
    assert result["avg_margin"] > 0
