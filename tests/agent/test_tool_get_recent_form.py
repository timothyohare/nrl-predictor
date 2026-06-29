import boto3
import pytest
from moto import mock_aws

from v1.agent.tools.recent_form import get_recent_form

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
        for i in range(6):
            tbl.put_item(Item={
                "matchId": f"panthers-v-opponent-{i}",
                "scoredAt": f"2026-0{3+i//4}-{10+i:02d}T10:00:00Z",
                "homeTeam": "Panthers",
                "awayTeam": f"Team{i}",
                "homeScore": 24,
                "awayScore": 14,
                "winner": "Panthers",
                "margin": 10,
                "matchState": "FullTime",
            })
        yield tbl


def test_returns_recent_form(ddb_table):
    result = get_recent_form("Panthers", n=5, table=ddb_table)
    assert len(result["results"]) == 5


def test_returns_fewer_than_n_if_not_enough(ddb_table):
    result = get_recent_form("Storm", n=5, table=ddb_table)
    assert result["results"] == []


def test_results_sorted_descending(ddb_table):
    result = get_recent_form("Panthers", n=6, table=ddb_table)
    dates = [r["scoredAt"] for r in result["results"]]
    assert dates == sorted(dates, reverse=True)


def test_includes_momentum(ddb_table):
    result = get_recent_form("Panthers", n=6, table=ddb_table)
    assert "momentum" in result
    assert result["momentum"]["weighted_win_rate"] == 1.0
    assert result["momentum"]["streak"] == "W6"
    assert result["momentum"]["momentum_direction"] == "stable"
