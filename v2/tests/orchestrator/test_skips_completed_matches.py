"""The orchestrator must not re-predict matches that have already finished.

NRL.com's ``round=current`` draw endpoint stays pinned to the just-finished round until
the following week's draw is published — it does not advance the moment full-time hits.
The local daily cron (v2/scripts/daily_update.sh) fires the orchestrator with
``round: "current"`` every day regardless, so every week there was a window (observed
2026-08-02 and 2026-08-09, ~11:00 UTC) where the orchestrator scraped a round whose
matches were already FullTime and re-ran the full agent fan-out — writing a "prediction"
generated after the real result was already known (contaminating round 16, 18, 20, 21,
22, 23 metrics). A match already at FullTime has nothing left to predict; the orchestrator
must skip it instead of fanning the agent out for it.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import boto3
import pytest
from moto import mock_aws

import v2.orchestrator.lambda_handler as oh


def _match(slug, match_state="Pre"):
    return SimpleNamespace(
        match_id=slug, round_number=22, home_team="Knights", away_team="Dragons",
        venue="McDonald Jones", kick_off="", match_state=match_state,
        match_centre_url=f"/draw/nrl-premiership/2026/round-22/{slug}/",
    )


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("TEAMS_TABLE", "teams")
    monkeypatch.setenv("RAW_BUCKET", "bucket")
    monkeypatch.setenv("AGENT_FUNCTION_NAME", "agent-fn")
    monkeypatch.setenv("AGENT_INVOKE_STAGGER_SECONDS", "0")

    monkeypatch.setattr(oh, "fetch_draw", lambda s, r: {"fixtures": []})
    monkeypatch.setattr(oh, "save_raw", lambda *a, **k: None)

    def _fail_sheet(url):  # a real re-scrape here would be the leak vector — must not be called
        raise AssertionError(f"team-sheet scrape must not run for a finished match: {url}")
    monkeypatch.setattr(oh, "fetch_team_sheet_page", _fail_sheet)

    fake_lambda = MagicMock()
    real_client = boto3.client

    def fake_client(name, *a, **k):
        return fake_lambda if name == "lambda" else real_client(name, *a, **k)
    monkeypatch.setattr(oh.boto3, "client", fake_client)

    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        table = ddb.create_table(
            TableName="teams",
            KeySchema=[{"AttributeName": "teamId", "KeyType": "HASH"},
                       {"AttributeName": "round", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "teamId", "AttributeType": "S"},
                                  {"AttributeName": "round", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        yield fake_lambda, table


def test_fully_completed_round_is_skipped_entirely(setup, monkeypatch):
    """All matches already FullTime -> no agent fan-out, no lock even taken."""
    fake_lambda, _ = setup
    monkeypatch.setattr(oh, "parse_draw", lambda raw: [
        _match("round-22-knights-v-dragons", "FullTime"),
        _match("round-22-storm-v-bulldogs", "FullTime"),
    ])

    result = oh.lambda_handler({"season": 2026, "round": "current"}, None)

    assert result["agent_triggered"] == []
    assert result["skipped"] == "already_played"
    assert fake_lambda.invoke.call_count == 0


def test_partially_completed_round_predicts_only_pending_matches(setup, monkeypatch):
    """Some matches already played (e.g. Thursday night) while others haven't kicked off
    yet — only the pending ones should get a fresh prediction."""
    fake_lambda, _ = setup
    monkeypatch.setattr(oh, "parse_draw", lambda raw: [
        _match("round-22-knights-v-dragons", "FullTime"),
        _match("round-22-storm-v-bulldogs", "Pre"),
    ])

    result = oh.lambda_handler({"season": 2026, "round": "current"}, None)

    assert result["agent_triggered"] == ["round-22-storm-v-bulldogs"]
    assert fake_lambda.invoke.call_count == 1


def test_no_matches_finished_behaves_as_before(setup, monkeypatch):
    fake_lambda, _ = setup
    monkeypatch.setattr(oh, "parse_draw", lambda raw: [
        _match("round-22-knights-v-dragons", "Pre"),
    ])

    result = oh.lambda_handler({"season": 2026, "round": "current"}, None)

    assert result["agent_triggered"] == ["round-22-knights-v-dragons"]
    assert "skipped" not in result
