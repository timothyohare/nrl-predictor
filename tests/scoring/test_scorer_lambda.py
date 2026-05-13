import boto3
import pytest
from moto import mock_aws
from unittest.mock import patch

PRED_TABLE = "predictions"
RESULTS_TABLE = "results"
METRICS_TABLE = "metrics"
MATCH_ID = "panthers-v-broncos-20260515"


@pytest.fixture
def aws_env(monkeypatch):
    monkeypatch.setenv("PREDICTIONS_TABLE", PRED_TABLE)
    monkeypatch.setenv("RESULTS_TABLE", RESULTS_TABLE)
    monkeypatch.setenv("METRICS_TABLE", METRICS_TABLE)


@pytest.fixture
def tables():
    with mock_aws():
        client = boto3.client("dynamodb", region_name="ap-southeast-2")
        for name, pk, sk in [
            (PRED_TABLE, "matchId", "generatedAt"),
            (RESULTS_TABLE, "matchId", "scoredAt"),
            (METRICS_TABLE, "period", "metricName"),
        ]:
            client.create_table(
                TableName=name,
                KeySchema=[
                    {"AttributeName": pk, "KeyType": "HASH"},
                    {"AttributeName": sk, "KeyType": "RANGE"},
                ],
                AttributeDefinitions=[
                    {"AttributeName": pk, "AttributeType": "S"},
                    {"AttributeName": sk, "AttributeType": "S"},
                ],
                BillingMode="PAY_PER_REQUEST",
            )
        ddb = boto3.resource("dynamodb", region_name="ap-southeast-2")
        pred = ddb.Table(PRED_TABLE)
        results = ddb.Table(RESULTS_TABLE)
        pred.put_item(Item={
            "matchId": MATCH_ID,
            "generatedAt": "2026-05-15T20:00:00Z",
            "predicted_winner": "Panthers",
            "predicted_margin": 10,
            "confidence": "HIGH",
            "roundNumber": 12,
            "season": 2026,
        })
        results.put_item(Item={
            "matchId": MATCH_ID,
            "scoredAt": "2026-05-16T11:30:00Z",
            "homeTeam": "Panthers",
            "awayTeam": "Broncos",
            "homeScore": 24,
            "awayScore": 18,
            "winner": "Panthers",
            "margin": 6,
            "matchState": "FullTime",
        })
        yield ddb


def test_scorer_lambda_writes_scored_result(aws_env, tables):
    from scoring.lambda_handler import lambda_handler
    with patch("scoring.lambda_handler.aggregate_round"):
        lambda_handler({"matchId": MATCH_ID, "round": 12, "season": 2026}, {})
    results_tbl = tables.Table(RESULTS_TABLE)
    items = results_tbl.scan()["Items"]
    scored = [i for i in items if "correct_pick" in i]
    assert len(scored) == 1
    assert scored[0]["correct_pick"] is True


def test_scorer_lambda_invokes_metrics_aggregation(aws_env, tables):
    from scoring.lambda_handler import lambda_handler
    with patch("scoring.lambda_handler.aggregate_round") as mock_agg:
        lambda_handler({"matchId": MATCH_ID, "round": 12, "season": 2026}, {})
    mock_agg.assert_called_once()
