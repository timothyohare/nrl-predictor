import boto3
import pytest
from moto import mock_aws
from agent.tools.lessons import get_lessons

TABLE = "retrospectives"


@pytest.fixture
def ddb_table():
    with mock_aws():
        boto3.client("dynamodb", region_name="ap-southeast-2").create_table(
            TableName=TABLE,
            KeySchema=[
                {"AttributeName": "matchId", "KeyType": "HASH"},
                {"AttributeName": "generatedAt", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "matchId", "AttributeType": "S"},
                {"AttributeName": "generatedAt", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        tbl = boto3.resource("dynamodb", region_name="ap-southeast-2").Table(TABLE)
        tbl.put_item(Item={
            "matchId": "round-10-panthers-v-storm",
            "generatedAt": "2026-05-10T10:00:00Z",
            "lesson": "Weight defensive record more heavily; Storm less reliant on individuals.",
            "verdict": "Prediction wrong — Storm won.",
            "roundNumber": 10,
            "season": 2026,
        })
        tbl.put_item(Item={
            "matchId": "round-11-bulldogs-v-roosters",
            "generatedAt": "2026-05-17T10:00:00Z",
            "lesson": "Bulldogs home advantage at Accor is worth an extra 4 points.",
            "verdict": "Correct pick.",
            "roundNumber": 11,
            "season": 2026,
        })
        tbl.put_item(Item={
            "matchId": "round-9-panthers-v-eels",
            "generatedAt": "2026-05-03T10:00:00Z",
            "lesson": "Derby form is unreliable — ignore season ladder position.",
            "verdict": "Prediction wrong.",
            "roundNumber": 9,
            "season": 2026,
        })
        tbl.put_item(Item={
            "matchId": "round-5-cowboys-v-broncos",
            "generatedAt": "2025-04-10T10:00:00Z",
            "lesson": "North Queensland heat affects visiting teams.",
            "verdict": "Correct pick.",
            "roundNumber": 5,
            "season": 2025,
        })
        yield tbl


def test_returns_lessons_for_season(ddb_table):
    results = get_lessons(season=2026, table=ddb_table)
    assert len(results) == 3


def test_returns_sorted_by_recency(ddb_table):
    results = get_lessons(season=2026, table=ddb_table)
    dates = [r["generatedAt"] for r in results]
    assert dates == sorted(dates, reverse=True)


def test_filters_by_team(ddb_table):
    results = get_lessons(season=2026, team="panthers", table=ddb_table)
    assert len(results) == 2
    assert all("panthers" in r["matchId"] for r in results)


def test_respects_limit(ddb_table):
    results = get_lessons(season=2026, limit=1, table=ddb_table)
    assert len(results) == 1


def test_returns_only_lesson_fields(ddb_table):
    results = get_lessons(season=2026, table=ddb_table)
    for r in results:
        assert "lesson" in r
        assert "matchId" in r
        assert "roundNumber" in r


def test_empty_when_no_matches(ddb_table):
    results = get_lessons(season=2024, table=ddb_table)
    assert results == []
