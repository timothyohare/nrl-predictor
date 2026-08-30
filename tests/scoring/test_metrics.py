from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

from scoring.metrics import (
    RoundMetrics,
    aggregate_market_season,
    aggregate_round,
    aggregate_season,
)

RESULTS_TABLE = "results"
METRICS_TABLE = "metrics"
ODDS_TABLE = "odds"


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
        # confidence: 4 HIGH (3 correct), 4 MEDIUM (3 correct), 2 LOW (1 correct)
        confidences = ["HIGH", "HIGH", "HIGH", "HIGH", "MEDIUM", "MEDIUM", "MEDIUM", "MEDIUM", "LOW", "LOW"]
        for i in range(10):
            results_tbl.put_item(Item={
                "matchId": f"match-{i}",
                "scoredAt": "2026-05-17T12:00:00Z",
                "roundNumber": 12,
                "season": 2026,
                "correct_pick": i < 7,
                "predicted_margin_error": i % 5,
                "brier_component": str(0.05 + i * 0.01),
                "confidence": confidences[i],
                "prompt_version": "v1.1",
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


def test_aggregate_season_writes_confidence_calibration(tables):
    results_tbl, metrics_tbl = tables
    aggregate_season(season=2026, results_table=results_tbl, metrics_table=metrics_tbl)

    # HIGH: i=0..3 → all 4 correct (i < 7 is True for all)
    high = metrics_tbl.get_item(Key={"period": "2026-season", "metricName": "pick_rate_high_confidence"})
    assert "Item" in high
    assert high["Item"]["total"] == 4
    assert high["Item"]["correct_picks"] == 4

    # MEDIUM: i=4..7 → i=4,5,6 correct, i=7 wrong → 3 correct
    medium = metrics_tbl.get_item(Key={"period": "2026-season", "metricName": "pick_rate_medium_confidence"})
    assert medium["Item"]["total"] == 4
    assert medium["Item"]["correct_picks"] == 3

    # LOW: i=8,9 → both wrong (i >= 7) → 0 correct
    low = metrics_tbl.get_item(Key={"period": "2026-season", "metricName": "pick_rate_low_confidence"})
    assert low["Item"]["total"] == 2
    assert low["Item"]["correct_picks"] == 0


def test_aggregate_season_writes_prompt_version_calibration(tables):
    results_tbl, metrics_tbl = tables
    aggregate_season(season=2026, results_table=results_tbl, metrics_table=metrics_tbl)
    pv = metrics_tbl.get_item(Key={"period": "2026-season", "metricName": "pick_rate_prompt_v1_1"})
    assert "Item" in pv
    assert pv["Item"]["total"] == 10
    assert pv["Item"]["correct_picks"] == 7


def test_aggregate_round_no_results_returns_zeroed_metrics_and_writes_nothing(tables):
    """A round with no scored rows short-circuits before any metric write (metrics.py:73)."""
    results_tbl, metrics_tbl = tables
    m = aggregate_round(99, 2026, results_tbl, metrics_tbl)
    assert (m.total, m.correct_picks, m.pick_rate) == (0, 0, 0.0)
    assert "Item" not in metrics_tbl.get_item(
        Key={"period": "2026-round-99", "metricName": "pick_rate"}
    )


def test_aggregate_season_no_results_writes_nothing(tables):
    """An empty season short-circuits before any metric write (metrics.py:116)."""
    results_tbl, metrics_tbl = tables
    aggregate_season(season=2099, results_table=results_tbl, metrics_table=metrics_tbl)
    assert "Item" not in metrics_tbl.get_item(
        Key={"period": "2099-season", "metricName": "pick_rate"}
    )


# --- aggregate_market_season (betting-market accuracy) --------------------------


@pytest.fixture
def market_tables():
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="ap-southeast-2")
        client = boto3.client("dynamodb", region_name="ap-southeast-2")
        for name, pk, sk in [
            (ODDS_TABLE, "matchId", "scrapedAt"),
            (RESULTS_TABLE, "matchId", "scoredAt"),
            (METRICS_TABLE, "period", "metricName"),
        ]:
            client.create_table(
                TableName=name,
                KeySchema=[
                    {"AttributeName": pk, "KeyType": "HASH"},
                    {"AttributeName": sk, "KeyType": "RANGE"},
                ],
                AttributeDefinitions=[
                    {"AttributeName": pk, "AttributeType": "S"},
                    {"AttributeName": sk, "AttributeType": "S"},
                ],
                BillingMode="PAY_PER_REQUEST",
            )
        yield ddb.Table(ODDS_TABLE), ddb.Table(RESULTS_TABLE), ddb.Table(METRICS_TABLE)


def _put_odds(odds_tbl, match_id, *, favourite="Panthers", margin="8.5",
              scraped_at="2026-05-16T08:00:00Z", season=2026):
    odds_tbl.put_item(Item={
        "matchId": match_id,
        "scrapedAt": scraped_at,
        "market_favourite": favourite,
        "market_margin": Decimal(margin),
        "implied_home_prob": Decimal("0.62"),
        "implied_away_prob": Decimal("0.38"),
        "roundNumber": 12,
        "season": season,
    })


def _put_result(results_tbl, match_id, *, winner="Panthers", margin=10,
                home_team="Panthers", season=2026):
    results_tbl.put_item(Item={
        "matchId": match_id,
        "scoredAt": "2026-05-17T11:30:00Z",
        "winner": winner,
        "margin": margin,
        "homeTeam": home_team,
        "awayTeam": "Broncos",
        "roundNumber": 12,
        "season": season,
    })


def test_aggregate_market_season_writes_market_metrics(market_tables):
    odds_tbl, results_tbl, metrics_tbl = market_tables
    # match A: market favourite (Panthers) wins -> correct pick
    _put_odds(odds_tbl, "round-12-a-v-b", favourite="Panthers", margin="8")
    _put_result(results_tbl, "round-12-a-v-b", winner="Panthers", margin=12, home_team="Panthers")
    # match B: market favourite (Storm) loses -> incorrect pick
    _put_odds(odds_tbl, "round-12-c-v-d", favourite="Storm", margin="4")
    _put_result(results_tbl, "round-12-c-v-d", winner="Sharks", margin=6, home_team="Storm")

    aggregate_market_season(2026, odds_tbl, results_tbl, metrics_tbl)

    pick_rate = metrics_tbl.get_item(
        Key={"period": "2026-season", "metricName": "market_pick_rate"}
    )["Item"]
    assert pick_rate["total"] == 2
    assert pick_rate["correct_picks"] == 1
    assert float(pick_rate["value"]) == pytest.approx(0.5)
    assert "Item" in metrics_tbl.get_item(
        Key={"period": "2026-season", "metricName": "market_mean_margin_error"}
    )
    assert "Item" in metrics_tbl.get_item(
        Key={"period": "2026-season", "metricName": "market_brier_score"}
    )


def test_aggregate_market_season_dedupes_to_most_recent_scraped_odds(market_tables):
    odds_tbl, results_tbl, metrics_tbl = market_tables
    mid = "round-12-a-v-b"
    # stale scrape has the wrong favourite; the corrected later scrape is right
    _put_odds(odds_tbl, mid, favourite="Broncos", margin="3", scraped_at="2026-05-15T08:00:00Z")
    _put_odds(odds_tbl, mid, favourite="Panthers", margin="9", scraped_at="2026-05-16T20:00:00Z")
    _put_result(results_tbl, mid, winner="Panthers", margin=10, home_team="Panthers")

    aggregate_market_season(2026, odds_tbl, results_tbl, metrics_tbl)

    pick_rate = metrics_tbl.get_item(
        Key={"period": "2026-season", "metricName": "market_pick_rate"}
    )["Item"]
    assert pick_rate["total"] == 1  # two odds rows collapse to one match
    assert pick_rate["correct_picks"] == 1  # scored off the most-recent (Panthers) row


def test_aggregate_market_season_no_odds_returns_early(market_tables):
    odds_tbl, results_tbl, metrics_tbl = market_tables
    _put_result(results_tbl, "round-12-a-v-b")
    aggregate_market_season(2026, odds_tbl, results_tbl, metrics_tbl)
    assert metrics_tbl.scan()["Items"] == []


def test_aggregate_market_season_all_matches_unplayed_returns_early(market_tables):
    odds_tbl, results_tbl, metrics_tbl = market_tables
    # odds present, but no result rows -> score_market raises for every match -> total 0
    _put_odds(odds_tbl, "round-12-a-v-b")
    _put_odds(odds_tbl, "round-12-c-v-d")
    aggregate_market_season(2026, odds_tbl, results_tbl, metrics_tbl)
    assert metrics_tbl.scan()["Items"] == []
