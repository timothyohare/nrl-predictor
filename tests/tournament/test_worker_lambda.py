"""Tests for the tournament worker Lambda's variant_type dispatch. See docs/plans/10, Phase 2."""
import os
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

from v1.tournament.worker_lambda import lambda_handler

PROMPT_VARIANTS_TABLE = "prompt_variants"
SIM_TABLE = "simulation_predictions"
RESULTS_TABLE = "results"

MATCH_IDS = ["round-13-panthers-v-broncos"]

BASE_EVENT = {
    "variantId": "some-variant",
    "variantVersion": "2026-06-01T00:00:00Z",
    "matchIds": MATCH_IDS,
    "round": 13,
    "season": 2026,
}


@pytest.fixture(autouse=True)
def env():
    with patch.dict(os.environ, {
        "PROMPT_VARIANTS_TABLE": PROMPT_VARIANTS_TABLE,
        "SIMULATION_PREDICTIONS_TABLE": SIM_TABLE,
        "RESULTS_TABLE": RESULTS_TABLE,
    }):
        yield


@pytest.fixture
def tables():
    with mock_aws():
        client = boto3.client("dynamodb", region_name="ap-southeast-2")
        client.create_table(
            TableName=PROMPT_VARIANTS_TABLE,
            KeySchema=[
                {"AttributeName": "variantId", "KeyType": "HASH"},
                {"AttributeName": "version", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "variantId", "AttributeType": "S"},
                {"AttributeName": "version", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
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
        yield boto3.resource("dynamodb", region_name="ap-southeast-2")


def _put_variant(ddb, variant_id, version, **extra):
    ddb.Table(PROMPT_VARIANTS_TABLE).put_item(Item={
        "variantId": variant_id,
        "version": version,
        "active": True,
        **extra,
    })


class TestVariantNotFound:
    def test_returns_error_without_calling_either_runner(self, tables):
        event = {**BASE_EVENT, "variantId": "missing", "variantVersion": "v1"}
        with patch("v1.tournament.worker_lambda.run_variant_for_round") as prompt_runner, \
             patch("v1.tournament.worker_lambda.run_stats_variant_for_round") as stats_runner:
            result = lambda_handler(event, None)

        assert result["status"] == "error"
        prompt_runner.assert_not_called()
        stats_runner.assert_not_called()


class TestPromptVariantDispatch:
    def test_default_variant_type_uses_prompt_runner(self, tables):
        # No variant_type field at all — existing 8 seeded variants predate this
        # field, so the default must route to the original LLM path unchanged.
        _put_variant(tables, "baseline", "v1", prompt_template="You are an NRL analyst.")
        with patch("v1.tournament.worker_lambda.run_variant_for_round", return_value=[{"pk": "x"}]) as prompt_runner, \
             patch("v1.tournament.worker_lambda.run_stats_variant_for_round") as stats_runner:
            result = lambda_handler({**BASE_EVENT, "variantId": "baseline", "variantVersion": "v1"}, None)

        assert result["status"] == "ok"
        prompt_runner.assert_called_once()
        stats_runner.assert_not_called()

    def test_explicit_prompt_type_uses_prompt_runner(self, tables):
        _put_variant(tables, "baseline", "v1", prompt_template="...", variant_type="prompt")
        with patch("v1.tournament.worker_lambda.run_variant_for_round", return_value=[{"pk": "x"}]) as prompt_runner, \
             patch("v1.tournament.worker_lambda.run_stats_variant_for_round") as stats_runner:
            lambda_handler({**BASE_EVENT, "variantId": "baseline", "variantVersion": "v1"}, None)

        prompt_runner.assert_called_once()
        stats_runner.assert_not_called()


class TestStatsVariantDispatch:
    def test_stats_model_type_uses_stats_runner(self, tables):
        _put_variant(tables, "stats-elo-v1", "v1", variant_type="stats_model")
        with patch("v1.tournament.worker_lambda.run_variant_for_round") as prompt_runner, \
             patch("v1.tournament.worker_lambda.run_stats_variant_for_round", return_value=[{"pk": "x"}]) as stats_runner:
            result = lambda_handler({**BASE_EVENT, "variantId": "stats-elo-v1", "variantVersion": "v1"}, None)

        assert result["status"] == "ok"
        stats_runner.assert_called_once()
        prompt_runner.assert_not_called()
        _, kwargs = stats_runner.call_args
        assert kwargs["variant_id"] == "stats-elo-v1"
        assert kwargs["match_ids"] == MATCH_IDS
        assert kwargs["round_number"] == 13
        assert kwargs["season"] == 2026

    def test_stats_variant_does_not_wait_for_stagger(self, tables):
        # The stats variant makes no external API calls, so there's nothing to
        # rate-limit — it shouldn't sleep for initialDelaySeconds/staggerSeconds
        # the way the LLM path does.
        _put_variant(tables, "stats-elo-v1", "v1", variant_type="stats_model")
        event = {**BASE_EVENT, "variantId": "stats-elo-v1", "variantVersion": "v1",
                  "initialDelaySeconds": 999}
        with patch("v1.tournament.worker_lambda.run_stats_variant_for_round", return_value=[]), \
             patch("v1.tournament.worker_lambda.time") as mock_time:
            lambda_handler(event, None)

        mock_time.sleep.assert_not_called()
