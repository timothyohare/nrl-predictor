import boto3
import pytest
from decimal import Decimal
from moto import mock_aws
from api.predictions import lambda_handler

TABLE = "predictions"


@pytest.fixture
def aws_env(monkeypatch):
    monkeypatch.setenv("PREDICTIONS_TABLE", TABLE)


@pytest.fixture
def table():
    with mock_aws():
        boto3.client("dynamodb", region_name="ap-southeast-2").create_table(
            TableName=TABLE,
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
        tbl = boto3.resource("dynamodb", region_name="ap-southeast-2").Table(TABLE)
        tbl.put_item(Item={
            "matchId": "panthers-v-broncos",
            "generatedAt": "2026-05-15T20:00:00Z",
            "roundNumber": 12,
            "season": 2026,
            "predicted_winner": "Panthers",
            "predicted_margin": 10,
            "confidence": "HIGH",
            "key_factors": ["Forward pack"],
            "reasoning": "x" * 200,
            "status": "OK",
            "staleness_flag": False,
        })
        yield tbl


def test_returns_predictions_for_round(aws_env, table):
    response = lambda_handler({"pathParameters": {"round": "12"}, "queryStringParameters": {}}, {})
    assert response["statusCode"] == 200
    import json
    body = json.loads(response["body"])
    assert len(body) == 1
    assert body[0]["predicted_winner"] == "Panthers"


def test_returns_staleness_field(aws_env, table):
    import json
    response = lambda_handler({"pathParameters": {"round": "12"}, "queryStringParameters": {}}, {})
    body = json.loads(response["body"])
    assert "staleness_flag" in body[0]


def test_returns_404_when_no_predictions(aws_env, table):
    response = lambda_handler({"pathParameters": {"round": "99"}, "queryStringParameters": {}}, {})
    assert response["statusCode"] == 404
