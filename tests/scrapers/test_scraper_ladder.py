import json
from pathlib import Path
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

from scrapers.nrl.ladder import lambda_handler, parse_ladder
from scrapers.shared.models import LadderPosition

FIXTURE = Path(__file__).parent.parent / "fixtures" / "nrl_ladder.json"


@pytest.fixture
def ladder_data():
    return json.loads(FIXTURE.read_text())


def test_parse_returns_ladder_positions(ladder_data):
    ladder = parse_ladder(ladder_data)
    assert all(isinstance(p, LadderPosition) for p in ladder)


def test_parse_returns_17_items(ladder_data):
    assert len(parse_ladder(ladder_data)) == 17


def test_parse_first_position_fields(ladder_data):
    pos = parse_ladder(ladder_data)[0]
    assert pos.position == 1
    assert pos.team_name == "panthers"
    assert pos.played == 15
    assert pos.wins == 12
    assert pos.losses == 3
    assert pos.draws == 0
    assert pos.points == 28
    assert pos.for_against_diff == 258
    # The live feed no longer carries a percentage; parser defaults it.
    assert pos.percentage == 0.0


def test_parse_sorted_by_position(ladder_data):
    ladder = parse_ladder(ladder_data)
    positions = [p.position for p in ladder]
    assert positions == sorted(positions)


@mock_aws
def test_lambda_handler_writes_to_dynamo_and_s3(ladder_data, monkeypatch):
    boto3.client("dynamodb", region_name="ap-southeast-2").create_table(
        TableName="teams",
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
    boto3.client("s3", region_name="ap-southeast-2").create_bucket(
        Bucket="test-bucket",
        CreateBucketConfiguration={"LocationConstraint": "ap-southeast-2"},
    )
    monkeypatch.setenv("TEAMS_TABLE", "teams")
    monkeypatch.setenv("RAW_BUCKET", "test-bucket")

    with patch("scrapers.nrl.ladder.fetch_ladder", return_value=ladder_data):
        lambda_handler({"season": 2026}, {})

    table = boto3.resource("dynamodb", region_name="ap-southeast-2").Table("teams")
    item = table.get_item(Key={"teamId": "ladder#2026", "round": "current"})
    assert "Item" in item
