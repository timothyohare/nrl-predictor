import json
from datetime import UTC, datetime
from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

from v1.api.tournament import _serialise, lambda_handler

TABLE = "variant_metrics"


@pytest.fixture
def aws_env(monkeypatch):
    monkeypatch.setenv("VARIANT_METRICS_TABLE", TABLE)


@pytest.fixture
def table():
    with mock_aws():
        boto3.client("dynamodb", region_name="ap-southeast-2").create_table(
            TableName=TABLE,
            KeySchema=[
                {"AttributeName": "variantId", "KeyType": "HASH"},
                {"AttributeName": "period", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "variantId", "AttributeType": "S"},
                {"AttributeName": "period", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        tbl = boto3.resource("dynamodb", region_name="ap-southeast-2").Table(TABLE)
        yield tbl


def _seed(tbl, variant_id, period, pick_rate):
    tbl.put_item(Item={
        "variantId": variant_id,
        "period": period,
        "pick_rate": Decimal(str(pick_rate)),
        "correct_picks": 6,
        "total_picks": 8,
        "avg_margin_error": Decimal("4.5"),
        "brier_score": Decimal("0.2"),
        "rounds_active": 3,
    })


def test_returns_503_when_not_configured(monkeypatch):
    monkeypatch.delenv("VARIANT_METRICS_TABLE", raising=False)
    response = lambda_handler({}, {})
    assert response["statusCode"] == 503
    assert json.loads(response["body"]) == {"error": "Tournament not configured"}


def test_returns_leaderboard_ordered_by_pick_rate_desc(aws_env, table):
    _seed(table, "aggressive", "2026-season", 0.55)
    _seed(table, "balanced", "2026-season", 0.72)
    _seed(table, "conservative", "2026-season", 0.61)

    response = lambda_handler({"queryStringParameters": {"season": "2026"}}, {})

    assert response["statusCode"] == 200
    assert response["headers"]["Cache-Control"] == "public, max-age=300"
    body = json.loads(response["body"])
    assert body["season"] == 2026
    assert [row["variantId"] for row in body["leaderboard"]] == [
        "balanced",
        "conservative",
        "aggressive",
    ]
    # Decimal cells came back as JSON floats
    assert body["leaderboard"][0]["pick_rate"] == 0.72
    assert isinstance(body["leaderboard"][0]["pick_rate"], float)


def test_season_query_param_is_honoured(aws_env, table):
    _seed(table, "balanced", "2025-season", 0.9)
    _seed(table, "balanced", "2026-season", 0.1)

    response = lambda_handler({"queryStringParameters": {"season": "2025"}}, {})

    body = json.loads(response["body"])
    assert body["season"] == 2025
    assert len(body["leaderboard"]) == 1
    assert body["leaderboard"][0]["pick_rate"] == 0.9


def test_season_defaults_to_current_utc_year(aws_env, table):
    response = lambda_handler({}, {})
    body = json.loads(response["body"])
    assert body["season"] == datetime.now(UTC).year
    assert body["leaderboard"] == []


def test_serialise_converts_decimal_and_rejects_other_types():
    assert _serialise(Decimal("1.25")) == 1.25
    assert isinstance(_serialise(Decimal("1.25")), float)
    with pytest.raises(TypeError):
        _serialise(object())
