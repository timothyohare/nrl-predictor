from datetime import UTC, datetime, timedelta

import boto3
import pytest
from moto import mock_aws

from v1.agent.tools.team_sheet import ToolError, get_team_sheet

TABLE = "teams"


def _seed(table, match_id="panthers-v-broncos", round_num="12", hours_old=1):
    scraped_at = (datetime.now(UTC) - timedelta(hours=hours_old)).isoformat()
    table.put_item(Item={
        "teamId": match_id,
        "round": round_num,
        "homeTeam": "Panthers",
        "awayTeam": "Broncos",
        "homePlayers": [],
        "awayPlayers": [],
        "matchState": "Pre",
        "kickOff": "2026-05-16T09:50:00Z",
        "scraped_at": scraped_at,
    })


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
        yield boto3.resource("dynamodb", region_name="ap-southeast-2").Table(TABLE)


def test_returns_team_sheet(ddb_table):
    _seed(ddb_table)
    result = get_team_sheet("panthers-v-broncos", round_number=12, table=ddb_table)
    assert result["homeTeam"] == "Panthers"


def test_raises_if_not_found(ddb_table):
    with pytest.raises(ToolError):
        get_team_sheet("no-such-match", round_number=12, table=ddb_table)


def test_raises_if_stale(ddb_table):
    _seed(ddb_table, hours_old=25)
    with pytest.raises(ToolError, match="stale"):
        get_team_sheet("panthers-v-broncos", round_number=12, table=ddb_table)
