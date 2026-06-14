from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

from agent.budget import BudgetExceeded

PRED_TABLE = "predictions"
USAGE_TABLE = "claude_usage"

_VALID_PREDICTION = {
    "predicted_winner": "Panthers",
    "predicted_margin": 10,
    "confidence": "HIGH",
    "key_factors": ["Forward pack", "Home ground"],
    "reasoning": "x" * 200,
    "data_freshness": "2026-05-15T10:00:00Z",
    "model_used": "claude-haiku-4-5-20251001",
    "generated_at": "2026-05-15T11:00:00Z",
}


@pytest.fixture
def aws_env(monkeypatch):
    monkeypatch.setenv("PREDICTIONS_TABLE", PRED_TABLE)
    monkeypatch.setenv("CLAUDE_USAGE_TABLE", USAGE_TABLE)
    monkeypatch.setenv("MONTHLY_BUDGET_USD", "18")


@pytest.fixture
def ddb_tables():
    with mock_aws():
        client = boto3.client("dynamodb", region_name="ap-southeast-2")
        client.create_table(
            TableName=PRED_TABLE,
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
        client.create_table(
            TableName=USAGE_TABLE,
            KeySchema=[
                {"AttributeName": "yearMonth", "KeyType": "HASH"},
                {"AttributeName": "invokedAt", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "yearMonth", "AttributeType": "S"},
                {"AttributeName": "invokedAt", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        yield boto3.resource("dynamodb", region_name="ap-southeast-2")


def test_lambda_handler_writes_prediction(aws_env, ddb_tables):
    from agent.lambda_handler import lambda_handler
    with patch("agent.lambda_handler.run_agent", return_value=_VALID_PREDICTION), \
         patch("agent.lambda_handler.check_budget"):
        lambda_handler({"matchId": "panthers-v-broncos", "round": 12, "is_finals": False}, {})
    table = ddb_tables.Table(PRED_TABLE)
    result = table.scan()
    assert result["Count"] == 1
    assert result["Items"][0]["predicted_winner"] == "Panthers"
    assert result["Items"][0]["generation"] == 1


def test_lambda_handler_increments_generation(aws_env, ddb_tables):
    from agent.lambda_handler import lambda_handler
    pred_1 = {**_VALID_PREDICTION, "generated_at": "2026-05-15T10:00:00Z"}
    pred_2 = {**_VALID_PREDICTION, "generated_at": "2026-05-16T10:00:00Z"}
    with patch("agent.lambda_handler.run_agent", side_effect=[pred_1, pred_2]), \
         patch("agent.lambda_handler.check_budget"):
        lambda_handler({"matchId": "panthers-v-broncos", "round": 12, "is_finals": False}, {})
        lambda_handler({"matchId": "panthers-v-broncos", "round": 12, "is_finals": False}, {})
    table = ddb_tables.Table(PRED_TABLE)
    items = sorted(table.scan()["Items"], key=lambda x: x["generatedAt"])
    assert items[0]["generation"] == 1
    assert items[1]["generation"] == 2


def test_lambda_handler_serves_cached_on_budget_exceeded(aws_env, ddb_tables):
    from agent.lambda_handler import lambda_handler
    # Pre-seed a cached prediction
    table = ddb_tables.Table(PRED_TABLE)
    table.put_item(Item={
        "matchId": "panthers-v-broncos",
        "generatedAt": "2026-05-14T10:00:00Z",
        **_VALID_PREDICTION,
    })
    with patch("agent.lambda_handler.check_budget", side_effect=BudgetExceeded("over budget")):
        lambda_handler({"matchId": "panthers-v-broncos", "round": 12, "is_finals": False}, {})
    result = table.scan()
    # Should have added a staleness-flagged record
    items = result["Items"]
    stale = [i for i in items if i.get("staleness_flag")]
    assert len(stale) == 1


def test_lambda_handler_writes_failed_status_on_error(aws_env, ddb_tables):
    from agent.lambda_handler import lambda_handler
    with patch("agent.lambda_handler.run_agent", side_effect=RuntimeError("agent crashed")), \
         patch("agent.lambda_handler.check_budget"):
        lambda_handler({"matchId": "panthers-v-broncos", "round": 12, "is_finals": False}, {})
    table = ddb_tables.Table(PRED_TABLE)
    items = table.scan()["Items"]
    failed = [i for i in items if i.get("status") == "FAILED"]
    assert len(failed) == 1
