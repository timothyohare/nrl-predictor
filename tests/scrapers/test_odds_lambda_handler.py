"""Tests for the odds scraper Lambda handler.

Regression coverage for the missing EventBridge schedule: the odds scraper
was deployed but never invoked in production because no rule targeted it.
Every other scheduled scraper/orchestrator in this repo accepts
`{"round": "current"}` and resolves it via the draw API (see
v1/orchestrator/lambda_handler.py, v1/orchestrator/coverage_check.py) — this
handler didn't, so simply adding a schedule with the same event shape those
other targets use would have silently produced zero matched odds (the
teams-table scan would filter on the literal string "current"). This test
locks in "current" resolution so the schedule added in infra/v1_stack.py
actually joins odds to matches.
"""
from decimal import Decimal
from unittest.mock import MagicMock, patch

import boto3
import pytest
from moto import mock_aws

TEAMS_TABLE = "teams"
ODDS_TABLE = "odds"

SAMPLE_API_RESPONSE = [
    {
        "id": "abc123",
        "commence_time": "2026-06-07T09:50:00Z",
        "home_team": "Penrith Panthers",
        "away_team": "Canterbury Bulldogs",
        "bookmakers": [
            {
                "key": "sportsbet",
                "markets": [
                    {"key": "h2h", "outcomes": [
                        {"name": "Penrith Panthers", "price": 1.45},
                        {"name": "Canterbury Bulldogs", "price": 2.80},
                    ]},
                ],
            },
        ],
    },
]


@pytest.fixture
def aws_env(monkeypatch):
    monkeypatch.setenv("TEAMS_TABLE", TEAMS_TABLE)
    monkeypatch.setenv("ODDS_TABLE", ODDS_TABLE)
    monkeypatch.setenv("ODDS_API_KEY", "test-key")


@pytest.fixture
def tables():
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="ap-southeast-2")
        teams_table = ddb.create_table(
            TableName=TEAMS_TABLE,
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
        odds_table = ddb.create_table(
            TableName=ODDS_TABLE,
            KeySchema=[
                {"AttributeName": "matchId", "KeyType": "HASH"},
                {"AttributeName": "scrapedAt", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "matchId", "AttributeType": "S"},
                {"AttributeName": "scrapedAt", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        teams_table.put_item(Item={
            "teamId": "panthers#home", "round": "15", "matchId": "round-15-panthers-v-bulldogs", "team": "Panthers",
        })
        teams_table.put_item(Item={
            "teamId": "bulldogs#away", "round": "15", "matchId": "round-15-panthers-v-bulldogs", "team": "Bulldogs",
        })
        yield teams_table, odds_table


def test_current_round_resolves_via_draw_api_before_matching_odds(aws_env, tables):
    """The 'current' sentinel (the shape every EventBridge target uses) must
    resolve to a real round number, not be compared literally against the
    teams table's numeric round field."""
    from scrapers.odds.lambda_handler import lambda_handler

    fake_match = MagicMock(round_number=15)
    with patch("scrapers.odds.lambda_handler.fetch_draw", return_value={"fixtures": []}) as fetch_mock, \
         patch("scrapers.odds.lambda_handler.parse_draw", return_value=[fake_match]), \
         patch("scrapers.odds.lambda_handler.fetch_odds", return_value=SAMPLE_API_RESPONSE):
        result = lambda_handler({"season": 2026, "round": "current"}, {})

    fetch_mock.assert_called_once_with(2026, "current")
    assert result["round"] == 15
    assert result["matches"] == 1

    _, odds_table = tables
    item = odds_table.scan()["Items"][0]
    assert item["matchId"] == "round-15-panthers-v-bulldogs"
    assert item["roundNumber"] == Decimal("15")
    # put_item must not choke on the scraper's native floats (odds/margins).
    assert item["home_odds"] == Decimal("1.45")


def test_explicit_round_number_skips_draw_fetch(aws_env, tables):
    from scrapers.odds.lambda_handler import lambda_handler

    with patch("scrapers.odds.lambda_handler.fetch_draw") as fetch_mock, \
         patch("scrapers.odds.lambda_handler.fetch_odds", return_value=SAMPLE_API_RESPONSE):
        result = lambda_handler({"season": 2026, "round": 15}, {})

    fetch_mock.assert_not_called()
    assert result["matches"] == 1


# ── 2026-08-18 incident regression lock: the-odds-api.com 401 INVALID_KEY ─────

def test_odds_api_401_invalid_key_fails_cleanly_and_writes_nothing(aws_env, tables):
    """2026-08-18: the-odds-api.com key lapsed and every call came back
    401 INVALID_KEY. The handler must degrade to a no-op (structured
    {"matches": 0} return, nothing written), never raise."""
    from scrapers.odds.lambda_handler import lambda_handler

    unauthorized = MagicMock(status_code=401, text='{"message":"INVALID_KEY"}')
    with patch("scrapers.odds.scraper.requests.get", return_value=unauthorized) as http_mock:
        result = lambda_handler({"season": 2026, "round": 15}, {})

    http_mock.assert_called_once()
    assert result == {"matches": 0}

    _, odds_table = tables
    assert odds_table.scan()["Count"] == 0


def test_empty_api_response_writes_nothing(aws_env, tables):
    """An empty payload from the odds API is a no-op, not an error."""
    from scrapers.odds.lambda_handler import lambda_handler

    with patch("scrapers.odds.lambda_handler.fetch_odds", return_value=[]):
        result = lambda_handler({"season": 2026, "round": 15}, {})

    assert result == {"matches": 0}
    _, odds_table = tables
    assert odds_table.scan()["Count"] == 0


def test_current_round_with_no_draw_matches_leaves_round_matches_empty(aws_env, tables):
    """`round: "current"` that resolves to no fixtures -> round_number is None,
    the teams-table scan is skipped and nothing matches."""
    from scrapers.odds.lambda_handler import lambda_handler

    with patch("scrapers.odds.lambda_handler.fetch_draw", return_value={"fixtures": []}), \
         patch("scrapers.odds.lambda_handler.parse_draw", return_value=[]), \
         patch("scrapers.odds.lambda_handler.fetch_odds", return_value=SAMPLE_API_RESPONSE):
        result = lambda_handler({"season": 2026, "round": "current"}, {})

    assert result == {"matches": 0, "round": None}
    _, odds_table = tables
    assert odds_table.scan()["Count"] == 0


def test_api_key_falls_back_to_secrets_manager_when_env_unset(tables, monkeypatch):
    """With no ODDS_API_KEY in the environment the handler must pull the key
    from Secrets Manager and pass it through to fetch_odds."""
    monkeypatch.setenv("TEAMS_TABLE", TEAMS_TABLE)
    monkeypatch.setenv("ODDS_TABLE", ODDS_TABLE)
    monkeypatch.delenv("ODDS_API_KEY", raising=False)

    from scrapers.odds.lambda_handler import lambda_handler

    boto3.client("secretsmanager", region_name="ap-southeast-2").create_secret(
        Name="nrl-predictor/odds-api-key", SecretString="sm-secret-key",
    )

    with patch("scrapers.odds.lambda_handler.fetch_odds", return_value=[]) as odds_mock:
        lambda_handler({"season": 2026, "round": 15}, {})

    assert odds_mock.call_args.kwargs["api_key"] == "sm-secret-key"
