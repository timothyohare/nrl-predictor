import logging
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

from scrapers.shared.models import Match

MATCHES = [
    Match(
        match_id=f"round-20-{pair}",
        home_team=pair.split("-v-")[0],
        away_team=pair.split("-v-")[1],
        venue="Accor Stadium",
        round_number=20,
        kick_off="2026-07-17T09:50:00Z",
        match_state="Upcoming",
    )
    for pair in ["panthers-v-broncos", "sharks-v-knights", "roosters-v-storm"]
]


@pytest.fixture
def aws_env(monkeypatch):
    monkeypatch.setenv("PREDICTIONS_TABLE", "predictions")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-southeast-2")


@pytest.fixture
def predictions_table():
    with mock_aws():
        client = boto3.client("dynamodb", region_name="ap-southeast-2")
        client.create_table(
            TableName="predictions",
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
        yield boto3.resource("dynamodb", region_name="ap-southeast-2").Table("predictions")


def _put(table, match_id: str, status: str, generated_at: str = "2026-07-14T23:45:00Z"):
    table.put_item(Item={
        "matchId": match_id,
        "generatedAt": generated_at,
        "roundNumber": 20,
        "status": status,
    })


def _run(event=None):
    from v1.orchestrator.coverage_check import lambda_handler

    with patch("v1.orchestrator.coverage_check.fetch_draw", return_value={}), \
         patch("v1.orchestrator.coverage_check.parse_draw", return_value=MATCHES):
        return lambda_handler(event or {"season": 2026, "round": "current"}, {})


def test_reports_missing_matches(aws_env, predictions_table, caplog):
    _put(predictions_table, "round-20-panthers-v-broncos", "OK")
    _put(predictions_table, "round-20-sharks-v-knights", "FAILED")
    # roosters-v-storm has no rows at all

    with caplog.at_level(logging.WARNING):
        result = _run()

    assert result["round"] == 20
    assert result["matches"] == 3
    assert result["ok"] == 1
    assert sorted(result["missing"]) == [
        "round-20-roosters-v-storm",
        "round-20-sharks-v-knights",
    ]
    warning = "\n".join(r.message for r in caplog.records if r.levelno >= logging.WARNING)
    assert "round-20-sharks-v-knights" in warning
    assert "round-20-roosters-v-storm" in warning


def test_full_coverage_reports_no_missing_and_no_warning(aws_env, predictions_table, caplog):
    for m in MATCHES:
        _put(predictions_table, m.match_id, "OK")

    with caplog.at_level(logging.WARNING):
        result = _run()

    assert result["missing"] == []
    assert result["ok"] == 3
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_failed_then_ok_generation_counts_as_covered(aws_env, predictions_table):
    """A match that FAILED then succeeded on a later generation is covered."""
    _put(predictions_table, "round-20-panthers-v-broncos", "FAILED", "2026-07-14T23:25:00Z")
    _put(predictions_table, "round-20-panthers-v-broncos", "OK", "2026-07-14T23:45:00Z")
    for m in MATCHES[1:]:
        _put(predictions_table, m.match_id, "OK")

    result = _run()
    assert result["missing"] == []


def test_emits_missing_predictions_metric(aws_env, predictions_table):
    _put(predictions_table, "round-20-panthers-v-broncos", "OK")

    _run()

    cw = boto3.client("cloudwatch", region_name="ap-southeast-2")
    metrics = cw.list_metrics(Namespace="NrlPredictor")["Metrics"]
    assert any(m["MetricName"] == "MissingPredictions" for m in metrics)


def test_no_matches_is_a_noop(aws_env, predictions_table):
    from v1.orchestrator.coverage_check import lambda_handler

    with patch("v1.orchestrator.coverage_check.fetch_draw", return_value={}), \
         patch("v1.orchestrator.coverage_check.parse_draw", return_value=[]):
        result = lambda_handler({"season": 2026, "round": "current"}, {})

    assert result == {"round": None, "matches": 0, "ok": 0, "missing": []}
