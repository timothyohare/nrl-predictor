import boto3
import pytest
from moto import mock_aws
from unittest.mock import patch, call
from scrapers.nrl.backfill import backfill_season
from tests.fixtures_helpers import make_draw_with_results


@pytest.fixture
def results_table():
    with mock_aws():
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
        yield boto3.resource("dynamodb", region_name="ap-southeast-2").Table("results")


@mock_aws
def test_backfill_calls_fetch_for_each_round(monkeypatch):
    monkeypatch.setenv("RESULTS_TABLE", "results")
    monkeypatch.setenv("RAW_BUCKET", "test-bucket")
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

    completed_round = make_draw_with_results(n_matches=2)
    empty_round = {"fixtures": []}

    with patch("scrapers.nrl.backfill.fetch_results") as mock_fetch, \
         patch("scrapers.nrl.backfill.time.sleep"):
        mock_fetch.side_effect = [completed_round, empty_round, completed_round]
        backfill_season(season=2026, max_round=3)
        assert mock_fetch.call_count == 3


@mock_aws
def test_backfill_writes_only_fulltime_results(monkeypatch):
    monkeypatch.setenv("RESULTS_TABLE", "results")
    monkeypatch.setenv("RAW_BUCKET", "test-bucket")
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

    completed = make_draw_with_results(n_matches=3)
    with patch("scrapers.nrl.backfill.fetch_results", return_value=completed), \
         patch("scrapers.nrl.backfill.time.sleep"):
        backfill_season(season=2026, max_round=1)

    table = boto3.resource("dynamodb", region_name="ap-southeast-2").Table("results")
    assert table.scan()["Count"] == 3


@mock_aws
def test_backfill_skips_empty_rounds_without_raising(monkeypatch):
    monkeypatch.setenv("RESULTS_TABLE", "results")
    monkeypatch.setenv("RAW_BUCKET", "test-bucket")
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

    with patch("scrapers.nrl.backfill.fetch_results", return_value={"fixtures": []}), \
         patch("scrapers.nrl.backfill.time.sleep"):
        backfill_season(season=2026, max_round=5)  # should not raise
