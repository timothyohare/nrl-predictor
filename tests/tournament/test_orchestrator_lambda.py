"""Tests for the tournament orchestrator Lambda.

Regression coverage for three bugs:
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
- The tournament orchestrator ran once a week (Saturday morning) regardless
  of when the round's matches actually kicked off. A round with an early
  (e.g. Thursday) match would have that match already finished by the time
  the tournament predicted it — a hindsight-contaminated "prediction" that
  silently inflated variant_metrics. Fixed by adding earlier-in-the-week
  schedules (mirroring the main orchestrator's cadence) plus two guards in
  this Lambda: skip matches whose kickoff has already passed, and skip
  matches this round already has a simulation_predictions row for (so
  running multiple times a week doesn't double-predict + double-count the
  same match in score_round's totals).
"""
import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import boto3
import pytest
from moto import mock_aws

FIXTURE = Path(__file__).parent.parent / "fixtures" / "nrl_draw_round12.json"

VARIANTS_TABLE = "prompt_variants"
SIM_PREDICTIONS_TABLE = "simulation_predictions"

# All fixture matches kick off 2026-05-16; freeze "now" well before that so
# existing tests (which don't care about the kickoff guard) keep predicting
# every fixture match, same as before that guard existed.
_BEFORE_ALL_KICKOFFS = datetime(2026, 5, 14, tzinfo=UTC)


@pytest.fixture
def draw_data():
    return json.loads(FIXTURE.read_text())


def _create_sim_predictions_table(client):
    client.create_table(
        TableName=SIM_PREDICTIONS_TABLE,
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


@pytest.fixture
def aws_env(monkeypatch):
    monkeypatch.setenv("PROMPT_VARIANTS_TABLE", VARIANTS_TABLE)
    monkeypatch.setenv("TOURNAMENT_WORKER_FUNCTION_ARN", "arn:aws:lambda:ap-southeast-2:123:function:worker")
    monkeypatch.setenv("SIMULATION_PREDICTIONS_TABLE", SIM_PREDICTIONS_TABLE)


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
        _create_sim_predictions_table(client)
        table = boto3.resource("dynamodb", region_name="ap-southeast-2").Table(VARIANTS_TABLE)
        table.put_item(Item={"variantId": "baseline", "version": "2026-06-03T21:03:30.181841+00:00", "active": True})
        table.put_item(
            Item={"variantId": "heavy-home-advantage", "version": "2026-06-03T21:03:30.181841+00:00", "active": True}
        )
        table.put_item(
            Item={"variantId": "retired-variant", "version": "2026-06-03T21:03:30.181841+00:00", "active": False}
        )
        yield table


@pytest.fixture
def sim_predictions_table(variants_table):
    """Shares the moto session opened by variants_table (both tables must coexist)."""
    return boto3.resource("dynamodb", region_name="ap-southeast-2").Table(SIM_PREDICTIONS_TABLE)


def test_scheduled_event_with_no_matchids_scrapes_the_draw_and_launches_workers(
    aws_env, variants_table, sim_predictions_table, draw_data
):
    """This is the exact EventBridge payload the schedule fires: no matchIds."""
    from v1.tournament.orchestrator_lambda import lambda_handler

    lambda_mock = MagicMock()
    with patch("v1.tournament.orchestrator_lambda.fetch_draw", return_value=draw_data), \
         patch("v1.tournament.orchestrator_lambda._utcnow", return_value=_BEFORE_ALL_KICKOFFS), \
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
        _create_sim_predictions_table(client)

        lambda_mock = MagicMock()
        with patch("v1.tournament.orchestrator_lambda.fetch_draw", return_value=draw_data), \
             patch("v1.tournament.orchestrator_lambda._utcnow", return_value=_BEFORE_ALL_KICKOFFS), \
             patch("v1.tournament.orchestrator_lambda.boto3.client", return_value=lambda_mock):
            result = lambda_handler({"season": 2026, "round": "current"}, {})

    assert result == {"status": "ok", "variants_launched": 0}
    lambda_mock.invoke.assert_not_called()


def test_already_started_matches_are_skipped(aws_env, variants_table, sim_predictions_table, draw_data):
    """A match whose kickoff has already passed must not be re-predicted —
    that's hindsight, not a prediction. The fixture's 3 matches kick off
    2026-05-16T09:50Z / 23:00Z / (none given, so treated as pending); freeze
    "now" between the first two so exactly one is skipped."""
    from v1.tournament.orchestrator_lambda import lambda_handler

    after_first_kickoff = datetime(2026, 5, 16, 10, 0, tzinfo=UTC)
    lambda_mock = MagicMock()
    with patch("v1.tournament.orchestrator_lambda.fetch_draw", return_value=draw_data), \
         patch("v1.tournament.orchestrator_lambda._utcnow", return_value=after_first_kickoff), \
         patch("v1.tournament.orchestrator_lambda.boto3.client", return_value=lambda_mock):
        result = lambda_handler({"season": 2026, "round": "current"}, {})

    assert result["status"] == "ok"
    assert result["matches"] == 2  # panthers-v-broncos already kicked off, excluded
    first_payload = json.loads(lambda_mock.invoke.call_args_list[0].kwargs["Payload"])
    assert "round-12-panthers-v-broncos" not in first_payload["matchIds"]


def test_already_predicted_matches_are_not_repredicted(aws_env, variants_table, sim_predictions_table, draw_data):
    """A match this round already has a simulation_predictions row for (from
    an earlier scheduled run this week) must be excluded, or score_round()
    would double-count it."""
    from v1.tournament.orchestrator_lambda import lambda_handler

    sim_predictions_table.put_item(Item={
        "pk": "round-12-panthers-v-broncos#baseline",
        "generatedAt": "2026-05-13T06:30:00+00:00",
        "matchId": "round-12-panthers-v-broncos",
        "roundNumber": 12,
        "season": 2026,
    })

    lambda_mock = MagicMock()
    with patch("v1.tournament.orchestrator_lambda.fetch_draw", return_value=draw_data), \
         patch("v1.tournament.orchestrator_lambda._utcnow", return_value=_BEFORE_ALL_KICKOFFS), \
         patch("v1.tournament.orchestrator_lambda.boto3.client", return_value=lambda_mock):
        result = lambda_handler({"season": 2026, "round": "current"}, {})

    assert result["status"] == "ok"
    assert result["matches"] == 2
    first_payload = json.loads(lambda_mock.invoke.call_args_list[0].kwargs["Payload"])
    assert "round-12-panthers-v-broncos" not in first_payload["matchIds"]


def test_all_matches_already_covered_returns_without_launching_workers(
    aws_env, variants_table, sim_predictions_table, draw_data
):
    from v1.tournament.orchestrator_lambda import lambda_handler

    for match_id in (
        "round-12-panthers-v-broncos",
        "round-12-sharks-v-bulldogs",
        "round-12-storm-v-roosters",
    ):
        sim_predictions_table.put_item(Item={
            "pk": f"{match_id}#baseline",
            "generatedAt": "2026-05-13T06:30:00+00:00",
            "matchId": match_id,
            "roundNumber": 12,
            "season": 2026,
        })

    lambda_mock = MagicMock()
    with patch("v1.tournament.orchestrator_lambda.fetch_draw", return_value=draw_data), \
         patch("v1.tournament.orchestrator_lambda._utcnow", return_value=_BEFORE_ALL_KICKOFFS), \
         patch("v1.tournament.orchestrator_lambda.boto3.client", return_value=lambda_mock):
        result = lambda_handler({"season": 2026, "round": "current"}, {})

    assert result == {"status": "ok", "variants_launched": 0}
    lambda_mock.invoke.assert_not_called()
