import json
import boto3
import pytest
from moto import mock_aws
from pathlib import Path
from unittest.mock import patch
from scrapers.nrl.results import parse_results, lambda_handler
from scrapers.shared.models import MatchResult

FIXTURE = Path(__file__).parent.parent / "fixtures" / "nrl_draw_round11_completed.json"


@pytest.fixture
def draw_data():
    return json.loads(FIXTURE.read_text())


def test_parse_returns_only_fulltime_matches(draw_data):
    results = parse_results(draw_data)
    assert len(results) == 3


def test_parse_returns_match_result_objects(draw_data):
    assert all(isinstance(r, MatchResult) for r in parse_results(draw_data))


def test_parse_correct_winner(draw_data):
    results = parse_results(draw_data)
    panthers = next(r for r in results if r.home_team == "Panthers")
    assert panthers.winner == "Panthers"
    assert panthers.home_score == 28
    assert panthers.away_score == 16
    assert panthers.margin == 12


def test_parse_away_team_win(draw_data):
    results = parse_results(draw_data)
    storm_match = next(r for r in results if r.away_team == "Storm")
    assert storm_match.winner == "Storm"
    assert storm_match.margin == 16


def test_parse_empty_fixtures():
    assert parse_results({"fixtures": []}) == []


def test_parse_no_completed_matches():
    data = {"fixtures": [{"matchCentreUrl": "/x/", "homeTeam": {"nickName": "A", "score": None},
                          "awayTeam": {"nickName": "B", "score": None}, "matchState": "Pre", "roundNumber": 1}]}
    assert parse_results(data) == []


@mock_aws
def test_lambda_handler_writes_results_to_dynamo(draw_data, monkeypatch):
    boto3.client("dynamodb", region_name="ap-southeast-2").create_table(
        TableName="results",
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
    boto3.client("s3", region_name="ap-southeast-2").create_bucket(
        Bucket="test-bucket",
        CreateBucketConfiguration={"LocationConstraint": "ap-southeast-2"},
    )
    monkeypatch.setenv("RESULTS_TABLE", "results")
    monkeypatch.setenv("RAW_BUCKET", "test-bucket")

    with patch("scrapers.nrl.results.fetch_results", return_value=draw_data):
        lambda_handler({"season": 2026, "round": 11}, {})

    table = boto3.resource("dynamodb", region_name="ap-southeast-2").Table("results")
    assert table.scan()["Count"] == 3
