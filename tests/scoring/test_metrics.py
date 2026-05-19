import boto3
import pytest
from moto import mock_aws
from scoring.metrics import aggregate_round, aggregate_season, RoundMetrics

RESULTS_TABLE = "results"
METRICS_TABLE = "metrics"


@pytest.fixture
def tables():
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="ap-southeast-2")
        client = boto3.client("dynamodb", region_name="ap-southeast-2")
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
        client.create_table(
            TableName=METRICS_TABLE,
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
        results_tbl = ddb.Table(RESULTS_TABLE)
        metrics_tbl = ddb.Table(METRICS_TABLE)
        # seed 10 scored results for round 12: 7 correct, 3 wrong
        for i in range(10):
            results_tbl.put_item(Item={
                "matchId": f"match-{i}",
                "scoredAt": "2026-05-17T12:00:00Z",
                "roundNumber": 12,
                "season": 2026,
                "correct_pick": i < 7,
                "predicted_margin_error": i % 5,
                "brier_component": str(0.05 + i * 0.01),
                "matchState": "FullTime",
            })
        yield results_tbl, metrics_tbl


def test_aggregate_round_returns_metrics(tables):
    results_tbl, metrics_tbl = tables
    m = aggregate_round(round_number=12, season=2026, results_table=results_tbl, metrics_table=metrics_tbl)
    assert isinstance(m, RoundMetrics)


def test_aggregate_round_correct_picks(tables):
    results_tbl, metrics_tbl = tables
    m = aggregate_round(12, 2026, results_tbl, metrics_tbl)
    assert m.correct_picks == 7
    assert m.total == 10
    assert m.pick_rate == pytest.approx(0.70)


def test_aggregate_round_writes_to_metrics_table(tables):
    results_tbl, metrics_tbl = tables
    aggregate_round(12, 2026, results_tbl, metrics_tbl)
    item = metrics_tbl.get_item(Key={"period": "2026-round-12", "metricName": "pick_rate"})
    assert "Item" in item


def test_aggregate_season_writes_season_record(tables):
    results_tbl, metrics_tbl = tables
    # also add 5 results for round 11 (3 correct) so season spans two rounds
    for i in range(5):
        results_tbl.put_item(Item={
            "matchId": f"r11-match-{i}",
            "scoredAt": "2026-05-10T12:00:00Z",
            "roundNumber": 11,
            "season": 2026,
            "correct_pick": i < 3,
            "predicted_margin_error": i % 4,
            "brier_component": str(0.04 + i * 0.01),
            "matchState": "FullTime",
        })
    aggregate_season(season=2026, results_table=results_tbl, metrics_table=metrics_tbl)
    item = metrics_tbl.get_item(Key={"period": "2026-season", "metricName": "pick_rate"})
    assert "Item" in item
    # 7 correct from round-12 fixture + 3 from round-11 = 10 out of 15
    assert item["Item"]["correct_picks"] == 10
    assert item["Item"]["total"] == 15
    assert float(item["Item"]["value"]) == pytest.approx(10 / 15)
