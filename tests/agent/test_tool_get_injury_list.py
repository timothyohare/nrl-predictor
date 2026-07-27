from datetime import UTC, datetime, timedelta

import boto3
import pytest
from moto import mock_aws

from v1.agent.tools.injury_list import get_injury_list

TABLE = "injuries"


def _seed(table, team="panthers", hours_old=5):
    """team defaults to the slugged form — scrapers/articles/lambda_handler.py
    always slugs the team before writing the pk."""
    scraped_at = (datetime.now(UTC) - timedelta(hours=hours_old)).isoformat()
    table.put_item(Item={
        "pk": f"injury#{team}#payne-haas",
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


def test_matches_real_slugged_pk_with_nickname_cased_arg(ddb_table):
    """Regression test for the confirmed production bug: the articles
    scraper always slugs the team before writing the pk, but the agent's
    tool schema documents "team nickname, e.g. Panthers" as the arg —
    get_injury_list must slug its own arg to match."""
    _seed(ddb_table, team="sea-eagles")
    results = get_injury_list("Sea Eagles", table=ddb_table)
    assert len(results) == 1


def test_already_slugged_arg_still_matches(ddb_table):
    _seed(ddb_table, team="sea-eagles")
    results = get_injury_list("sea-eagles", table=ddb_table)
    assert len(results) == 1
