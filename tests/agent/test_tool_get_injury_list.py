from datetime import UTC, datetime, timedelta

import boto3
import pytest
from moto import mock_aws

from v1.agent.tools.injury_list import get_injury_list

TABLE = "injuries"


def _seed(table, team="Panthers", hours_old=5):
    scraped_at = (datetime.now(UTC) - timedelta(hours=hours_old)).isoformat()
    table.put_item(Item={
        "pk": f"injury#{team}#Payne Haas",
        "sk": scraped_at,
        "player": "Payne Haas",
        "team": team,
        "status": "out",
        "detail": "calf strain",
        "scraped_at": scraped_at,
    })


@pytest.fixture
def ddb_table():
    with mock_aws():
        boto3.client("dynamodb", region_name="ap-southeast-2").create_table(
            TableName=TABLE,
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        yield boto3.resource("dynamodb", region_name="ap-southeast-2").Table(TABLE)


def test_returns_injuries_for_team(ddb_table):
    _seed(ddb_table)
    results = get_injury_list("Panthers", table=ddb_table)
    assert len(results) == 1
    assert results[0]["player"] == "Payne Haas"


def test_returns_empty_list_when_none(ddb_table):
    results = get_injury_list("Storm", table=ddb_table)
    assert results == []


def test_filters_records_older_than_48h(ddb_table):
    _seed(ddb_table, hours_old=50)
    results = get_injury_list("Panthers", table=ddb_table)
    assert results == []
