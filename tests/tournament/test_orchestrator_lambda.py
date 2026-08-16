"""Tests for the tournament orchestrator Lambda.

Regression coverage for two bugs:
- The scheduled (EventBridge) invocation never supplies matchIds, so the
  orchestrator silently no-op'd every week instead of scraping the draw
  itself like the main orchestrator does.
- `variant["version"]` was wrapped in `int(...)` before being sent to the
  worker payload, but the real `prompt_variants` table's `version` sort key
  is a STRING (an ISO timestamp written by seed_variants.py), not a number.
  Every scheduled run crashed with `ValueError` and the tournament never
  produced a single result. This file's table fixture below intentionally
  mirrors the real table's schema (STRING version) so this class of bug
  fails a test instead of only failing silently in production.
"""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import boto3
import pytest
from moto import mock_aws

FIXTURE = Path(__file__).parent.parent / "fixtures" / "nrl_draw_round12.json"

VARIANTS_TABLE = "prompt_variants"


@pytest.fixture
def draw_data():
    return json.loads(FIXTURE.read_text())


@pytest.fixture
def aws_env(monkeypatch):
    monkeypatch.setenv("PROMPT_VARIANTS_TABLE", VARIANTS_TABLE)
    monkeypatch.setenv("TOURNAMENT_WORKER_FUNCTION_ARN", "arn:aws:lambda:ap-southeast-2:123:function:worker")


def _create_variants_table(client):
    client.create_table(
        TableName=VARIANTS_TABLE,
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


@pytest.fixture
def variants_table():
    with mock_aws():
        client = boto3.client("dynamodb", region_name="ap-southeast-2")
        _create_variants_table(client)
        table = boto3.resource("dynamodb", region_name="ap-southeast-2").Table(VARIANTS_TABLE)
        table.put_item(Item={"variantId": "baseline", "version": "2026-06-03T21:03:30.181841+00:00", "active": True})
        table.put_item(
            Item={"variantId": "heavy-home-advantage", "version": "2026-06-03T21:03:30.181841+00:00", "active": True}
        )
        table.put_item(
            Item={"variantId": "retired-variant", "version": "2026-06-03T21:03:30.181841+00:00", "active": False}
        )
        yield table


def test_scheduled_event_with_no_matchids_scrapes_the_draw_and_launches_workers(
    aws_env, variants_table, draw_data
):
    """This is the exact EventBridge payload the schedule fires: no matchIds."""
    from v1.tournament.orchestrator_lambda import lambda_handler

    lambda_mock = MagicMock()
    with patch("v1.tournament.orchestrator_lambda.fetch_draw", return_value=draw_data), \
         patch("v1.tournament.orchestrator_lambda.boto3.client", return_value=lambda_mock):
        result = lambda_handler({"season": 2026, "round": "current"}, {})

    assert result["status"] == "ok"
    assert result["variants_launched"] == 2  # only the 2 active variants
    assert result["matches"] == 3  # 3 fixtures have matchCentreUrl in the fixture

    assert lambda_mock.invoke.call_count == 2
    first_payload = json.loads(lambda_mock.invoke.call_args_list[0].kwargs["Payload"])
    assert first_payload["round"] == 12
    assert first_payload["season"] == 2026
    assert len(first_payload["matchIds"]) == 3
    assert "round-12-panthers-v-broncos" in first_payload["matchIds"]
    assert first_payload["variantId"] in {"baseline", "heavy-home-advantage"}
    # variantVersion must round-trip as the same string used for the table's
    # sort key — int(...) here throws ValueError against the real schema.
    assert first_payload["variantVersion"] == "2026-06-03T21:03:30.181841+00:00"


def test_explicit_matchids_skip_the_draw_scrape(aws_env, variants_table):
    """Manual/debug invocations that already pass matchIds shouldn't hit the network."""
    from v1.tournament.orchestrator_lambda import lambda_handler

    lambda_mock = MagicMock()
    with patch("v1.tournament.orchestrator_lambda.fetch_draw") as fetch_mock, \
         patch("v1.tournament.orchestrator_lambda.boto3.client", return_value=lambda_mock):
        result = lambda_handler(
            {"season": 2026, "round": 12, "matchIds": ["round-12-panthers-v-broncos"]}, {}
        )

    fetch_mock.assert_not_called()
    assert result["variants_launched"] == 2
    assert result["matches"] == 1


def test_no_matches_in_draw_returns_without_launching_workers(aws_env, variants_table):
    from v1.tournament.orchestrator_lambda import lambda_handler

    lambda_mock = MagicMock()
    with patch("v1.tournament.orchestrator_lambda.fetch_draw", return_value={"fixtures": []}), \
         patch("v1.tournament.orchestrator_lambda.boto3.client", return_value=lambda_mock):
        result = lambda_handler({"season": 2026, "round": "current"}, {})

    assert result == {"status": "ok", "variants_launched": 0}
    lambda_mock.invoke.assert_not_called()


def test_no_active_variants_returns_without_launching_workers(aws_env, draw_data):
    from v1.tournament.orchestrator_lambda import lambda_handler

    with mock_aws():
        client = boto3.client("dynamodb", region_name="ap-southeast-2")
        _create_variants_table(client)

        lambda_mock = MagicMock()
        with patch("v1.tournament.orchestrator_lambda.fetch_draw", return_value=draw_data), \
             patch("v1.tournament.orchestrator_lambda.boto3.client", return_value=lambda_mock):
            result = lambda_handler({"season": 2026, "round": "current"}, {})

    assert result == {"status": "ok", "variants_launched": 0}
    lambda_mock.invoke.assert_not_called()
