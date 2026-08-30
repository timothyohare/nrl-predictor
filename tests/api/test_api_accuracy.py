from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

from v1.api.accuracy import _serialise, lambda_handler

TABLE = "metrics"


@pytest.fixture
def aws_env(monkeypatch):
    monkeypatch.setenv("METRICS_TABLE", TABLE)


@pytest.fixture
def table():
    with mock_aws():
        boto3.client("dynamodb", region_name="ap-southeast-2").create_table(
            TableName=TABLE,
            KeySchema=[
                {"AttributeName": "period", "KeyType": "HASH"},
                {"AttributeName": "metricName", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "period", "AttributeType": "S"},
                {"AttributeName": "metricName", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        tbl = boto3.resource("dynamodb", region_name="ap-southeast-2").Table(TABLE)
        tbl.put_item(Item={"period": "2026-season", "metricName": "pick_rate", "value": Decimal("0.65"), "correct_picks": 65, "total": 100})
        tbl.put_item(Item={"period": "2026-season", "metricName": "brier_score", "value": Decimal("0.12"), "correct_picks": 65, "total": 100})
        tbl.put_item(Item={"period": "2026-round-11", "metricName": "pick_rate", "value": Decimal("0.75"), "correct_picks": 6, "total": 8})
        yield tbl


def test_returns_accuracy_data(aws_env, table):
    import json
    response = lambda_handler({}, {})
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert "season" in body
    assert "rounds" in body


def test_response_has_no_cache_header(aws_env, table):
    response = lambda_handler({}, {})
    assert response["headers"].get("Cache-Control") == "no-store"


def test_raises_key_error_when_metrics_table_unset(monkeypatch):
    monkeypatch.delenv("METRICS_TABLE", raising=False)
    with pytest.raises(KeyError):
        lambda_handler({}, {})


def test_scan_paginates_past_one_page(aws_env, table):
    import json

    # Each item ~350KB; >3 exceeds the 1MB scan page so the handler must follow
    # LastEvaluatedKey or it silently drops metrics rows.
    for i in range(5):
        table.put_item(Item={
            "period": f"2026-round-{40 + i}",
            "metricName": "pick_rate",
            "value": Decimal("0.5"),
            "blob": "x" * 350_000,
        })

    response = lambda_handler({}, {})
    body = json.loads(response["body"])
    round_periods = {r["period"] for r in body["rounds"]}
    assert {f"2026-round-{40 + i}" for i in range(5)} <= round_periods


def test_serialise_converts_decimal_and_rejects_other_types():
    assert _serialise(Decimal("0.5")) == 0.5
    with pytest.raises(TypeError):
        _serialise(set())
