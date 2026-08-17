"""Tests for common/stats_model/ratings.py — shared by the offline backtest
(scripts/backtest_elo_model.py) and the live tournament stats variant
(v1/tournament/stats_variant_runner.py). See docs/plans/10."""
import boto3
import pytest
from moto import mock_aws

from common.stats_model.ratings import (
    STARTING_RATING,
    compute_ratings_as_of,
    load_canonical_results,
)

RESULTS_TABLE = "results"


@pytest.fixture
def results_table():
    with mock_aws():
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
        yield boto3.resource("dynamodb", region_name="ap-southeast-2").Table(RESULTS_TABLE)


def _put(table, match_id, home, away, home_score, away_score, scored_at="2026-06-01T00:00:00Z"):
    table.put_item(Item={
        "matchId": match_id,
        "scoredAt": scored_at,
        "homeTeam": home,
        "awayTeam": away,
        "homeScore": home_score,
        "awayScore": away_score,
        "winner": home if home_score > away_score else away,
        "margin": abs(home_score - away_score),
        "matchState": "FullTime",
    })


class TestLoadCanonicalResults:
    def test_excludes_legacy_unqualified_ids(self, results_table):
        _put(results_table, "round-12-panthers-v-broncos", "panthers", "broncos", 20, 10)
        _put(results_table, "panthers-v-broncos", "panthers", "broncos", 20, 10)

        results = load_canonical_results(results_table)

        assert [r["matchId"] for r in results] == ["round-12-panthers-v-broncos"]

    def test_dedupes_to_latest_scoredat(self, results_table):
        _put(results_table, "round-12-panthers-v-broncos", "panthers", "broncos", 20, 10,
             scored_at="2026-06-01T00:00:00Z")
        _put(results_table, "round-12-panthers-v-broncos", "panthers", "broncos", 22, 10,
             scored_at="2026-06-02T00:00:00Z")  # a correction

        results = load_canonical_results(results_table)

        assert len(results) == 1
        assert int(results[0]["homeScore"]) == 22

    def test_sorted_by_round(self, results_table):
        _put(results_table, "round-14-storm-v-roosters", "storm", "roosters", 18, 12)
        _put(results_table, "round-12-panthers-v-broncos", "panthers", "broncos", 20, 10)

        results = load_canonical_results(results_table)

        assert [r["matchId"] for r in results] == [
            "round-12-panthers-v-broncos", "round-14-storm-v-roosters",
        ]


class TestComputeRatingsAsOf:
    def test_no_history_returns_starting_rating(self, results_table):
        ratings = compute_ratings_as_of(load_canonical_results(results_table), before_round=12, home_advantage=55)
        assert ratings["panthers"] == STARTING_RATING

    def test_no_look_ahead_excludes_target_round(self, results_table):
        _put(results_table, "round-12-panthers-v-broncos", "panthers", "broncos", 40, 0)

        ratings_before = compute_ratings_as_of(
            load_canonical_results(results_table), before_round=12, home_advantage=55
        )
        assert ratings_before["panthers"] == STARTING_RATING
        assert ratings_before["broncos"] == STARTING_RATING

    def test_includes_earlier_rounds(self, results_table):
        _put(results_table, "round-12-panthers-v-broncos", "panthers", "broncos", 40, 0)

        ratings_after = compute_ratings_as_of(
            load_canonical_results(results_table), before_round=13, home_advantage=55
        )
        assert ratings_after["panthers"] > STARTING_RATING
        assert ratings_after["broncos"] < STARTING_RATING

    def test_deterministic(self, results_table):
        _put(results_table, "round-12-panthers-v-broncos", "panthers", "broncos", 24, 18)
        results = load_canonical_results(results_table)

        a = compute_ratings_as_of(results, before_round=13, home_advantage=55)
        b = compute_ratings_as_of(results, before_round=13, home_advantage=55)

        assert dict(a) == dict(b)
