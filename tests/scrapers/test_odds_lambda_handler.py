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
