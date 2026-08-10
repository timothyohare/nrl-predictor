"""Tests for load_match_context's is_finals derivation (v2/agent/lambda_handler.py)."""
import boto3
import pytest
from moto import mock_aws


@pytest.fixture
def teams_table():
    with mock_aws():
        client = boto3.client("dynamodb", region_name="ap-southeast-2")
        client.create_table(
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
        yield boto3.resource("dynamodb", region_name="ap-southeast-2").Table("teams")


@pytest.mark.parametrize("round_number,expected_is_finals", [
    (26, False),
    (27, False),  # last regular-season round — NOT finals
    (28, True),   # Finals Week 1
    (31, True),   # Grand Final
])
def test_load_match_context_is_finals_boundary(monkeypatch, teams_table, round_number, expected_is_finals):
    monkeypatch.setenv("TEAMS_TABLE", "teams")
    from v2.agent.lambda_handler import load_match_context

    match_id = f"round-{round_number}-storm-v-broncos"
    teams_table.put_item(Item={
        "teamId": match_id,
        "round": str(round_number),
        "homeTeam": "Storm",
        "awayTeam": "Broncos",
    })

    ctx = load_match_context(match_id, round_number, 2026)
    assert ctx["is_finals"] is expected_is_finals
