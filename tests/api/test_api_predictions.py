import json
from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

from v1.api.predictions import _serialise, lambda_handler

TABLE = "predictions"
RESULTS_TABLE = "results"
RETRO_TABLE = "retrospectives"
ODDS_TABLE = "odds"


def _make_table(name, sort_key):
    boto3.client("dynamodb", region_name="ap-southeast-2").create_table(
        TableName=name,
        KeySchema=[
            {"AttributeName": "matchId", "KeyType": "HASH"},
            {"AttributeName": sort_key, "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "matchId", "AttributeType": "S"},
            {"AttributeName": sort_key, "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    return boto3.resource("dynamodb", region_name="ap-southeast-2").Table(name)


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


def test_returns_400_for_non_integer_round(aws_env, table):
    # Found by gate-fuzz (CHG-0026): int() on the raw path param crashed the
    # handler for any non-numeric round — API Gateway passes strings through.
    import json
    response = lambda_handler({"pathParameters": {"round": "null"}, "queryStringParameters": {}}, {})
    assert response["statusCode"] == 400
    assert "error" in json.loads(response["body"])


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


def test_returns_all_matches_when_table_exceeds_one_scan_page(aws_env, table):
    """Scan pages are capped at 1MB and FilterExpression applies after the cut —
    the handler must paginate or matches silently vanish (prod round 20, 2026-07-15)."""
    import json
    matches = [f"round-20-team{i}a-v-team{i}b" for i in range(8)]
    for m in matches:
        table.put_item(Item={
            "matchId": m,
            "generatedAt": "2026-07-14T23:45:00Z",
            "roundNumber": 20,
            "season": 2026,
            "predicted_winner": "Panthers",
            "predicted_margin": 8,
            "confidence": "MEDIUM",
            "key_factors": ["x"],
            "reasoning": "x" * 300_000,  # ~300KB → 8 rows span multiple scan pages
            "status": "OK",
            "staleness_flag": False,
        })
    response = lambda_handler({"pathParameters": {"round": "20"}, "queryStringParameters": {}}, {})
    body = json.loads(response["body"])
    assert sorted(p["matchId"] for p in body) == sorted(matches)


def _predict(event_round="12"):
    return lambda_handler(
        {"pathParameters": {"round": event_round}, "queryStringParameters": {}}, {}
    )


# --- retrospective join ------------------------------------------------------

def test_retrospective_join_uses_newest_generated_at(aws_env, table, monkeypatch):
    monkeypatch.setenv("RETROSPECTIVES_TABLE", RETRO_TABLE)
    retro = _make_table(RETRO_TABLE, "generatedAt")
    retro.put_item(Item={
        "matchId": "panthers-v-broncos",
        "generatedAt": "2026-05-17T08:00:00Z",
        "roundNumber": 12,
        "verdict": "stale verdict",
        "lesson": "old lesson",
    })
    retro.put_item(Item={
        "matchId": "panthers-v-broncos",
        "generatedAt": "2026-05-18T09:00:00Z",
        "roundNumber": 12,
        "verdict": "fresh verdict",
        "hit_factors": ["forward pack"],
        "missed_factors": ["bench impact"],
        "what_actually_happened": "Panthers won comfortably.",
        "lesson": "new lesson",
    })

    body = json.loads(_predict()["body"])
    assert body[0]["retrospective"]["verdict"] == "fresh verdict"
    assert body[0]["retrospective"]["lesson"] == "new lesson"
    assert body[0]["retrospective"]["hit_factors"] == ["forward pack"]
    assert body[0]["retrospective"]["generated_at"] == "2026-05-18T09:00:00Z"


def test_retrospective_scan_failure_is_swallowed(aws_env, table, monkeypatch):
    # Table name points at a table that does not exist → scan raises, handler
    # must still return predictions without a retrospective block.
    monkeypatch.setenv("RETROSPECTIVES_TABLE", "retrospectives-missing")
    body = json.loads(_predict()["body"])
    assert len(body) == 1
    assert "retrospective" not in body[0]


# --- odds join + is_outlier ------------------------------------------------

@pytest.mark.parametrize(
    "market_favourite, market_margin, expected_outlier",
    [
        ("panthers", 8, False),   # agree on winner, |10-8| = 2 <= 6
        ("Broncos", 10, True),    # disagree on winner
        ("Panthers", 20, True),   # agree on winner but |10-20| = 10 > 6
    ],
)
def test_is_outlier_table_driven(
    aws_env, table, monkeypatch, market_favourite, market_margin, expected_outlier
):
    monkeypatch.setenv("ODDS_TABLE", ODDS_TABLE)
    odds = _make_table(ODDS_TABLE, "scrapedAt")
    odds.put_item(Item={
        "matchId": "panthers-v-broncos",
        "scrapedAt": "2026-05-15T09:00:00Z",
        "roundNumber": 12,
        "market_favourite": market_favourite,
        "market_margin": Decimal(str(market_margin)),
        "home_odds": Decimal("1.5"),
        "away_odds": Decimal("2.7"),
        "implied_home_prob": Decimal("0.66"),
        "implied_away_prob": Decimal("0.34"),
    })

    body = json.loads(_predict()["body"])
    assert body[0]["is_outlier"] is expected_outlier
    assert body[0]["odds"]["market_favourite"] == market_favourite
    assert body[0]["odds"]["market_margin"] == float(market_margin)
    assert isinstance(body[0]["odds"]["home_odds"], float)
    assert body[0]["odds"]["implied_away_prob"] == 0.34


# --- optional tables unset ------------------------------------------------

def test_optional_joins_absent_when_tables_unset(aws_env, table, monkeypatch):
    monkeypatch.delenv("RESULTS_TABLE", raising=False)
    monkeypatch.delenv("RETROSPECTIVES_TABLE", raising=False)
    monkeypatch.delenv("ODDS_TABLE", raising=False)

    response = _predict()
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert "result" not in body[0]
    assert "retrospective" not in body[0]
    assert "odds" not in body[0]
    assert "is_outlier" not in body[0]


def test_result_scan_failure_is_swallowed(aws_env, table, monkeypatch):
    monkeypatch.setenv("RESULTS_TABLE", "results-missing")
    body = json.loads(_predict()["body"])
    assert len(body) == 1
    assert "result" not in body[0]


def test_odds_scan_failure_is_swallowed(aws_env, table, monkeypatch):
    monkeypatch.setenv("ODDS_TABLE", "odds-missing")
    body = json.loads(_predict()["body"])
    assert len(body) == 1
    assert "odds" not in body[0]
    assert "is_outlier" not in body[0]


def test_serialise_rejects_non_decimal():
    assert _serialise(Decimal("2.5")) == 2.5
    with pytest.raises(TypeError):
        _serialise({"not": "serialisable"})
