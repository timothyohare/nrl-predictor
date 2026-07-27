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


def test_excludes_current_match_from_its_own_recent_form(ddb_table):
    """Regression test for a real data-leakage bug: if the match currently
    being analysed already has a row in the results table (e.g. re-running
    against an already-completed round), get_recent_form must not include
    that match's own result in the team's "recent form" — otherwise the
    tool hands the model the answer it's supposed to be predicting."""
    ddb_table.put_item(Item={
        "matchId": "round-21-panthers-v-knights",
        "scoredAt": "2026-07-27T11:00:00Z",
        "homeTeam": "Panthers",
        "awayTeam": "Knights",
        "homeScore": 30,
        "awayScore": 10,
        "winner": "Panthers",
        "margin": 20,
        "matchState": "FullTime",
    })

    result = get_recent_form(
        "Panthers", n=6, table=ddb_table, exclude_match_id="round-21-panthers-v-knights",
    )

    match_ids = [r["matchId"] for r in result["results"]]
    assert "round-21-panthers-v-knights" not in match_ids


def test_exclude_match_id_defaults_to_no_exclusion(ddb_table):
    """Backward compatible: omitting exclude_match_id changes nothing."""
    result = get_recent_form("Panthers", n=6, table=ddb_table)
    assert len(result["results"]) == 6
