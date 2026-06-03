"""Tests for tournament variant scorer."""
from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

from tournament.variant_scorer import score_round, aggregate_variant_season, get_leaderboard

SIM_TABLE = "simulation_predictions"
RESULTS_TABLE = "results"
VARIANT_METRICS_TABLE = "variant_metrics"

VARIANT_IDS = ["baseline", "heavy-home-advantage"]
MATCH_ID_1 = "round-12-panthers-v-broncos"
MATCH_ID_2 = "round-12-storm-v-roosters"


def _put_sim_prediction(table, match_id, variant_id, predicted_winner, predicted_margin=10,
                        confidence="HIGH", round_number=12, season=2026):
    table.put_item(Item={
        "pk": f"{match_id}#{variant_id}",
        "generatedAt": "2026-05-31T08:00:00Z",
        "matchId": match_id,
        "variantId": variant_id,
        "predicted_winner": predicted_winner,
        "predicted_margin": predicted_margin,
        "confidence": confidence,
        "roundNumber": round_number,
        "season": season,
    })


def _put_result(table, match_id, winner, margin=8, round_number=12, season=2026):
    table.put_item(Item={
        "matchId": match_id,
        "scoredAt": "2026-06-01T11:30:00Z",
        "winner": winner,
        "homeTeam": match_id.split("-v-")[0].split("-")[-1].capitalize(),
        "awayTeam": match_id.split("-v-")[1].split("-")[0].capitalize(),
        "margin": margin,
        "roundNumber": round_number,
        "season": season,
        "correct_pick": True,
    })


@pytest.fixture
def tables():
    with mock_aws():
        ddb_client = boto3.client("dynamodb", region_name="ap-southeast-2")
        for name, pk, sk in [
            (SIM_TABLE, "pk", "generatedAt"),
            (RESULTS_TABLE, "matchId", "scoredAt"),
            (VARIANT_METRICS_TABLE, "variantId", "period"),
        ]:
            ddb_client.create_table(
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
        ddb = boto3.resource("dynamodb", region_name="ap-southeast-2")
        sim_tbl = ddb.Table(SIM_TABLE)
        results_tbl = ddb.Table(RESULTS_TABLE)
        metrics_tbl = ddb.Table(VARIANT_METRICS_TABLE)
        yield sim_tbl, results_tbl, metrics_tbl


class TestScoreRound:
    def test_scores_correct_pick(self, tables):
        sim_tbl, results_tbl, metrics_tbl = tables
        _put_sim_prediction(sim_tbl, MATCH_ID_1, "baseline", "Panthers")
        _put_result(results_tbl, MATCH_ID_1, "Panthers", margin=12)

        score_round(12, 2026, sim_tbl, results_tbl, metrics_tbl)

        resp = metrics_tbl.get_item(Key={"variantId": "baseline", "period": "2026-round-12"})
        item = resp["Item"]
        assert item["correct_picks"] == 1
        assert item["total_picks"] == 1
        assert float(item["pick_rate"]) == 1.0

    def test_scores_wrong_pick(self, tables):
        sim_tbl, results_tbl, metrics_tbl = tables
        _put_sim_prediction(sim_tbl, MATCH_ID_1, "baseline", "Panthers")
        _put_result(results_tbl, MATCH_ID_1, "Broncos", margin=4)

        score_round(12, 2026, sim_tbl, results_tbl, metrics_tbl)

        resp = metrics_tbl.get_item(Key={"variantId": "baseline", "period": "2026-round-12"})
        item = resp["Item"]
        assert item["correct_picks"] == 0
        assert float(item["pick_rate"]) == 0.0

    def test_aggregates_multiple_matches(self, tables):
        sim_tbl, results_tbl, metrics_tbl = tables
        _put_sim_prediction(sim_tbl, MATCH_ID_1, "baseline", "Panthers")
        _put_sim_prediction(sim_tbl, MATCH_ID_2, "baseline", "Storm")
        _put_result(results_tbl, MATCH_ID_1, "Panthers", margin=8)
        _put_result(results_tbl, MATCH_ID_2, "Roosters", margin=4)  # wrong

        score_round(12, 2026, sim_tbl, results_tbl, metrics_tbl)

        resp = metrics_tbl.get_item(Key={"variantId": "baseline", "period": "2026-round-12"})
        item = resp["Item"]
        assert item["correct_picks"] == 1
        assert item["total_picks"] == 2
        assert abs(float(item["pick_rate"]) - 0.5) < 0.001

    def test_scores_multiple_variants_independently(self, tables):
        sim_tbl, results_tbl, metrics_tbl = tables
        # baseline: correct; heavy-home: wrong
        _put_sim_prediction(sim_tbl, MATCH_ID_1, "baseline", "Panthers")
        _put_sim_prediction(sim_tbl, MATCH_ID_1, "heavy-home-advantage", "Broncos")
        _put_result(results_tbl, MATCH_ID_1, "Panthers", margin=8)

        score_round(12, 2026, sim_tbl, results_tbl, metrics_tbl)

        baseline = metrics_tbl.get_item(Key={"variantId": "baseline", "period": "2026-round-12"})["Item"]
        heavy = metrics_tbl.get_item(Key={"variantId": "heavy-home-advantage", "period": "2026-round-12"})["Item"]
        assert baseline["correct_picks"] == 1
        assert heavy["correct_picks"] == 0

    def test_calculates_margin_error(self, tables):
        sim_tbl, results_tbl, metrics_tbl = tables
        _put_sim_prediction(sim_tbl, MATCH_ID_1, "baseline", "Panthers", predicted_margin=10)
        _put_result(results_tbl, MATCH_ID_1, "Panthers", margin=16)

        score_round(12, 2026, sim_tbl, results_tbl, metrics_tbl)

        resp = metrics_tbl.get_item(Key={"variantId": "baseline", "period": "2026-round-12"})
        assert float(resp["Item"]["avg_margin_error"]) == 6.0

    def test_skips_match_with_no_result(self, tables):
        sim_tbl, results_tbl, metrics_tbl = tables
        _put_sim_prediction(sim_tbl, MATCH_ID_1, "baseline", "Panthers")
        # No result for MATCH_ID_1

        score_round(12, 2026, sim_tbl, results_tbl, metrics_tbl)

        resp = metrics_tbl.get_item(Key={"variantId": "baseline", "period": "2026-round-12"})
        assert "Item" not in resp  # nothing written when no scored matches


class TestGetLeaderboard:
    def test_returns_variants_sorted_by_pick_rate(self, tables):
        sim_tbl, results_tbl, metrics_tbl = tables
        metrics_tbl.put_item(Item={
            "variantId": "baseline",
            "period": "2026-season",
            "pick_rate": Decimal("0.62"),
            "correct_picks": 16,
            "total_picks": 26,
            "avg_margin_error": Decimal("8.5"),
            "brier_score": Decimal("0.24"),
            "rounds_active": 4,
        })
        metrics_tbl.put_item(Item={
            "variantId": "heavy-home-advantage",
            "period": "2026-season",
            "pick_rate": Decimal("0.73"),
            "correct_picks": 19,
            "total_picks": 26,
            "avg_margin_error": Decimal("7.1"),
            "brier_score": Decimal("0.19"),
            "rounds_active": 4,
        })

        board = get_leaderboard(2026, metrics_tbl)

        assert len(board) == 2
        assert board[0]["variantId"] == "heavy-home-advantage"
        assert board[1]["variantId"] == "baseline"

    def test_returns_empty_list_when_no_data(self, tables):
        _, _, metrics_tbl = tables
        assert get_leaderboard(2026, metrics_tbl) == []
