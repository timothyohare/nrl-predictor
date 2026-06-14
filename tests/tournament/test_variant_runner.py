"""Tests for tournament variant runner."""
from unittest.mock import MagicMock, patch

import boto3
import pytest
from moto import mock_aws

from tournament.variant_runner import run_variant_for_round, run_variant_prediction

SIM_TABLE = "simulation_predictions"
MATCH_ID = "round-12-panthers-v-broncos"
VARIANT = {
    "variantId": "heavy-home-advantage",
    "version": "2026-06-01T00:00:00Z",
    "prompt_template": "You are an NRL analyst. Home advantage is worth 6 points.",
    "hypothesis": "Heavier home advantage weighting improves accuracy",
    "active": True,
}


def _fake_run_agent(match_id, match_context, client=None, system_prompt=None):
    return {
        "predicted_winner": "Panthers",
        "predicted_margin": 10,
        "confidence": "HIGH",
        "reasoning": "Panthers are strong at home.",
        "data_freshness": "2026-05-30T00:00:00Z",
        "model_used": "claude-haiku-4-5",
        "generated_at": "2026-05-31T08:00:00Z",
    }


@pytest.fixture
def sim_table():
    with mock_aws():
        client = boto3.client("dynamodb", region_name="ap-southeast-2")
        client.create_table(
            TableName=SIM_TABLE,
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "generatedAt", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "generatedAt", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        yield boto3.resource("dynamodb", region_name="ap-southeast-2").Table(SIM_TABLE)


class TestRunVariantPrediction:
    def test_calls_run_agent_with_variant_prompt(self):
        mock_client = MagicMock()
        with patch("tournament.variant_runner.run_agent", side_effect=_fake_run_agent) as mock_run:
            run_variant_prediction(
                match_id=MATCH_ID,
                variant=VARIANT,
                match_context={"round": 12},
                client=mock_client,
            )
        mock_run.assert_called_once_with(
            MATCH_ID,
            {"round": 12},
            client=mock_client,
            system_prompt=VARIANT["prompt_template"],
        )

    def test_returns_simulation_prediction_record(self):
        with patch("tournament.variant_runner.run_agent", side_effect=_fake_run_agent):
            result = run_variant_prediction(MATCH_ID, VARIANT, {"round": 12})

        assert result["matchId"] == MATCH_ID
        assert result["variantId"] == VARIANT["variantId"]
        assert result["pk"] == f"{MATCH_ID}#{VARIANT['variantId']}"
        assert result["predicted_winner"] == "Panthers"
        assert result["predicted_margin"] == 10
        assert result["confidence"] == "HIGH"
        assert "generatedAt" in result

    def test_truncates_reasoning_to_500_chars(self):
        long_reasoning = "X" * 800
        with patch("tournament.variant_runner.run_agent") as mock_run:
            mock_run.return_value = {**_fake_run_agent("", {}), "reasoning": long_reasoning}
            result = run_variant_prediction(MATCH_ID, VARIANT, {"round": 12})

        assert len(result["reasoning"]) <= 500

    def test_writes_to_sim_table_when_provided(self, sim_table):
        with patch("tournament.variant_runner.run_agent", side_effect=_fake_run_agent):
            result = run_variant_prediction(MATCH_ID, VARIANT, {"round": 12}, sim_table=sim_table)

        resp = sim_table.get_item(
            Key={"pk": result["pk"], "generatedAt": result["generatedAt"]}
        )
        assert "Item" in resp
        assert resp["Item"]["predicted_winner"] == "Panthers"


class TestRunVariantForRound:
    def test_calls_prediction_for_each_match(self):
        match_ids = ["round-12-panthers-v-broncos", "round-12-storm-v-roosters"]
        calls_made = []

        def fake_predict(match_id, variant, match_context, client=None, sim_table=None):
            calls_made.append(match_id)
            return {"pk": f"{match_id}#{variant['variantId']}", "generatedAt": "2026-05-31T08:00:00Z"}

        with patch("tournament.variant_runner.run_variant_prediction", side_effect=fake_predict):
            run_variant_for_round(
                variant=VARIANT,
                match_ids=match_ids,
                round_number=12,
                season=2026,
                stagger_seconds=0,
            )

        assert calls_made == match_ids

    def test_staggers_between_matches(self):
        match_ids = ["round-12-panthers-v-broncos", "round-12-storm-v-roosters"]

        def fake_predict(match_id, variant, match_context, client=None, sim_table=None):
            return {"pk": f"{match_id}#v", "generatedAt": "2026-05-31T08:00:00Z"}

        with patch("tournament.variant_runner.run_variant_prediction", side_effect=fake_predict), \
             patch("tournament.variant_runner.time") as mock_time:
            run_variant_for_round(
                variant=VARIANT,
                match_ids=match_ids,
                round_number=12,
                season=2026,
                stagger_seconds=12,
            )
            # Sleep called once (between 2nd and following matches, not before first)
            assert mock_time.sleep.call_count == 1
            mock_time.sleep.assert_called_with(12)

    def test_no_sleep_before_first_match(self):
        match_ids = ["round-12-panthers-v-broncos"]

        def fake_predict(match_id, variant, match_context, client=None, sim_table=None):
            return {"pk": f"{match_id}#v", "generatedAt": "2026-05-31T08:00:00Z"}

        with patch("tournament.variant_runner.run_variant_prediction", side_effect=fake_predict), \
             patch("tournament.variant_runner.time") as mock_time:
            run_variant_for_round(
                variant=VARIANT,
                match_ids=match_ids,
                round_number=12,
                season=2026,
                stagger_seconds=12,
            )
            mock_time.sleep.assert_not_called()
