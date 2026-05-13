import boto3
import pytest
from decimal import Decimal
from moto import mock_aws
from agent.tools.ladder import get_ladder

TABLE = "teams"


@pytest.fixture
def ddb_table():
    with mock_aws():
        boto3.client("dynamodb", region_name="ap-southeast-2").create_table(
            TableName=TABLE,
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
        tbl = boto3.resource("dynamodb", region_name="ap-southeast-2").Table(TABLE)
        tbl.put_item(Item={
            "teamId": "ladder#2026",
            "round": "current",
            "season": 2026,
            "positions": [
                {"position": 1, "team_name": "Panthers", "played": 11, "wins": 9,
                 "losses": 2, "draws": 0, "points": 18, "for_against_diff": 102,
                 "percentage": Decimal("158.3")},
                {"position": 2, "team_name": "Storm", "played": 11, "wins": 8,
                 "losses": 3, "draws": 0, "points": 16, "for_against_diff": 87,
                 "percentage": Decimal("142.1")},
            ],
            "scraped_at": "2026-05-15T10:00:00Z",
        })
        yield tbl


def test_returns_ladder(ddb_table):
    ladder = get_ladder(season=2026, table=ddb_table)
    assert len(ladder) == 2


def test_sorted_by_position(ddb_table):
    ladder = get_ladder(season=2026, table=ddb_table)
    positions = [p["position"] for p in ladder]
    assert positions == sorted(positions)


def test_returns_empty_list_if_no_ladder(ddb_table):
    ladder = get_ladder(season=2025, table=ddb_table)
    assert ladder == []
