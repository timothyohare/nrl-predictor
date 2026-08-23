"""Tests for the main-path stats predictor (v1/orchestrator/stats_predictor.py) —
the Phase 3 cutover from the Claude agent to the local Elo + Monte Carlo model.
See docs/plans/10-elo-monte-carlo-predictor.md.
"""
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

from scrapers.shared.models import Match

MODEL_ID = "stats-elo-v1"


@pytest.fixture
def tables():
    with mock_aws():
        client = boto3.client("dynamodb", region_name="ap-southeast-2")
        client.create_table(
            TableName="predictions",
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
        ddb = boto3.resource("dynamodb", region_name="ap-southeast-2")
        yield ddb.Table("predictions"), ddb.Table("results")


def _matches():
    return [
        Match(
            match_id="round-13-panthers-v-broncos",
            home_team="Panthers",
            away_team="Broncos",
            venue="BlueBet Stadium",
            round_number=13,
            kick_off="2026-06-01T09:00:00Z",
            match_state="Pre",
            match_centre_url="/draw/nrl-premiership/2026/round-13/panthers-v-broncos/",
        ),
        Match(
            match_id="round-13-storm-v-roosters",
            home_team="Storm",
            away_team="Roosters",
            venue="AAMI Park",
            round_number=13,
            kick_off="2026-06-01T23:00:00Z",
            match_state="Pre",
            match_centre_url="/draw/nrl-premiership/2026/round-13/storm-v-roosters/",
        ),
    ]


class TestPredictRound:
    def test_writes_one_ok_prediction_per_match(self, tables):
        from v1.orchestrator.stats_predictor import predict_round

        predictions_table, results_table = tables
        predicted = predict_round(_matches(), round_number=13, season=2026,
                                   predictions_table=predictions_table, results_table=results_table)

        assert predicted == ["round-13-panthers-v-broncos", "round-13-storm-v-roosters"]
        items = predictions_table.scan()["Items"]
        assert len(items) == 2
        for item in items:
            assert item["status"] == "OK"
            assert item["staleness_flag"] is False
            assert item["model_used"] == MODEL_ID
            assert item["prompt_version"] == MODEL_ID
            assert item["roundNumber"] == 13
            assert item["confidence"] in ("HIGH", "MEDIUM", "LOW")
            assert len(item["key_factors"]) >= 2
            assert item["generation"] == 1

    def test_predicted_winner_is_one_of_the_two_teams(self, tables):
        from v1.orchestrator.stats_predictor import predict_round

        predictions_table, results_table = tables
        predict_round(_matches()[:1], round_number=13, season=2026,
                       predictions_table=predictions_table, results_table=results_table)

        item = predictions_table.scan()["Items"][0]
        assert item["predicted_winner"] in ("panthers", "broncos")

    def test_generation_increments_across_runs(self, tables):
        from v1.orchestrator.stats_predictor import predict_round

        predictions_table, results_table = tables
        match = _matches()[:1]
        predict_round(match, round_number=13, season=2026,
                       predictions_table=predictions_table, results_table=results_table)
        predict_round(match, round_number=13, season=2026,
                       predictions_table=predictions_table, results_table=results_table)

        items = predictions_table.query(
            KeyConditionExpression="matchId = :m",
            ExpressionAttributeValues={":m": "round-13-panthers-v-broncos"},
        )["Items"]
        assert sorted(i["generation"] for i in items) == [1, 2]

    def test_one_match_failing_does_not_block_the_others(self, tables):
        from common.stats_model.predictor import predict_match as real_predict_match
        from v1.orchestrator.stats_predictor import predict_round

        predictions_table, results_table = tables

        def flaky_predict(home, away, *args, **kwargs):
            if home == "panthers":
                raise ValueError("boom")
            return real_predict_match(home, away, *args, **kwargs)

        with patch("v1.orchestrator.stats_predictor.predict_match", side_effect=flaky_predict):
            predicted = predict_round(_matches(), round_number=13, season=2026,
                                       predictions_table=predictions_table, results_table=results_table)

        assert predicted == ["round-13-storm-v-roosters"]
        items = {i["matchId"]: i for i in predictions_table.scan()["Items"]}
        assert items["round-13-panthers-v-broncos"]["status"] == "FAILED"
        assert items["round-13-storm-v-roosters"]["status"] == "OK"

    def test_no_agent_import(self):
        # Sanity guard for the whole point of the cutover: this module must not
        # touch the agent/Claude at all.
        import v1.orchestrator.stats_predictor as mod
        assert "run_agent" not in dir(mod)
