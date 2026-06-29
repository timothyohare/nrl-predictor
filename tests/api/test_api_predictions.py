
import boto3
import pytest
from moto import mock_aws

from v1.api.predictions import lambda_handler

TABLE = "predictions"
RESULTS_TABLE = "results"


@pytest.fixture
def aws_env(monkeypatch):
    monkeypatch.setenv("PREDICTIONS_TABLE", TABLE)
    monkeypatch.setenv("RESULTS_TABLE", RESULTS_TABLE)


@pytest.fixture
def table():
    with mock_aws():
        client = boto3.client("dynamodb", region_name="ap-southeast-2")
        client.create_table(
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
        client.create_table(
            TableName=RESULTS_TABLE,
            KeySchema=[
                {"AttributeName": "matchId", "KeyType": "HASH"},
                {"AttributeName": "scoredAt", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "matchId", "AttributeType": "S"},
                {"AttributeName": "scoredAt", "AttributeType": "S"},
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


def test_includes_result_when_match_is_scored(aws_env, table):
    import json
    results = boto3.resource("dynamodb", region_name="ap-southeast-2").Table(RESULTS_TABLE)
    results.put_item(Item={
        "matchId": "panthers-v-broncos",
        "scoredAt": "2026-05-16T10:00:00Z",
        "roundNumber": 12,
        "season": 2026,
        "homeTeam": "Panthers",
        "awayTeam": "Broncos",
        "homeScore": 24,
        "awayScore": 12,
        "winner": "Panthers",
        "margin": 12,
        "matchState": "FullTime",
    })

    response = lambda_handler({"pathParameters": {"round": "12"}, "queryStringParameters": {}}, {})
    body = json.loads(response["body"])
    assert "result" in body[0]
    r = body[0]["result"]
    assert r["winner"] == "Panthers"
    assert r["homeScore"] == 24
    assert r["awayScore"] == 12
    assert r["margin"] == 12


def test_omits_result_when_match_unplayed(aws_env, table):
    import json
    response = lambda_handler({"pathParameters": {"round": "12"}, "queryStringParameters": {}}, {})
    body = json.loads(response["body"])
    assert "result" not in body[0]


def test_picks_latest_result_when_multiple_scored_rows(aws_env, table):
    import json
    results = boto3.resource("dynamodb", region_name="ap-southeast-2").Table(RESULTS_TABLE)
    # Earlier, possibly-incorrect row
    results.put_item(Item={
        "matchId": "panthers-v-broncos",
        "scoredAt": "2026-05-16T10:00:00Z",
        "roundNumber": 12,
        "homeTeam": "Panthers",
        "awayTeam": "Broncos",
        "homeScore": 18,
        "awayScore": 18,
        "winner": "Draw",
        "margin": 0,
    })
    # Later, correct row (e.g. final score updated)
    results.put_item(Item={
        "matchId": "panthers-v-broncos",
        "scoredAt": "2026-05-16T11:00:00Z",
        "roundNumber": 12,
        "homeTeam": "Panthers",
        "awayTeam": "Broncos",
        "homeScore": 24,
        "awayScore": 18,
        "winner": "Panthers",
        "margin": 6,
    })

    response = lambda_handler({"pathParameters": {"round": "12"}, "queryStringParameters": {}}, {})
    body = json.loads(response["body"])
    assert body[0]["result"]["winner"] == "Panthers"
    assert body[0]["result"]["homeScore"] == 24
