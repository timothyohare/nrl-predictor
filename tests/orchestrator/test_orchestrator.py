import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import boto3
import pytest
from moto import mock_aws

from scrapers.nrl.team_sheet import TeamSheetNotFound

FIXTURE = Path(__file__).parent.parent / "fixtures" / "nrl_draw_round12.json"


@pytest.fixture
def draw_data():
    return json.loads(FIXTURE.read_text())


@pytest.fixture
def aws_env(monkeypatch):
    monkeypatch.setenv("TEAMS_TABLE", "teams")
    monkeypatch.setenv("RAW_BUCKET", "test-bucket")
    monkeypatch.setenv("AGENT_FUNCTION_NAME", "nrl-predictor-agent")
    # Disable the rate-limit stagger so tests run instantly
    monkeypatch.setenv("AGENT_INVOKE_STAGGER_SECONDS", "0")


@pytest.fixture
def ddb_and_s3():
    with mock_aws():
        client = boto3.client("dynamodb", region_name="ap-southeast-2")
        client.create_table(
            TableName="teams",
            KeySchema=[
                {"AttributeName": "teamId", "KeyType": "HASH"},
                {"AttributeName": "round", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "teamId", "AttributeType": "S"},
                {"AttributeName": "round", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        boto3.client("s3", region_name="ap-southeast-2").create_bucket(
            Bucket="test-bucket",
            CreateBucketConfiguration={"LocationConstraint": "ap-southeast-2"},
        )
        yield


def test_orchestrator_writes_draw_and_invokes_agent_per_match(
    aws_env, ddb_and_s3, draw_data
):
    from orchestrator.lambda_handler import lambda_handler

    lambda_mock = MagicMock()
    with patch("orchestrator.lambda_handler.fetch_draw", return_value=draw_data), \
         patch("orchestrator.lambda_handler.fetch_team_sheet_page", side_effect=TeamSheetNotFound("skip in test")), \
         patch("orchestrator.lambda_handler.boto3.client", return_value=lambda_mock):
        result = lambda_handler({"season": 2026, "round": 12}, {})

    # 3 fixtures have matchCentreUrl
    assert result["matches"] == 3
    # Each match should trigger one agent invocation
    assert len(result["agent_triggered"]) == 3
    assert "round-12-panthers-v-broncos" in result["agent_triggered"]

    # Verify the Lambda invoke calls
    assert lambda_mock.invoke.call_count == 3
    first_call = lambda_mock.invoke.call_args_list[0]
    assert first_call.kwargs["FunctionName"] == "nrl-predictor-agent"
    assert first_call.kwargs["InvocationType"] == "Event"
    payload = json.loads(first_call.kwargs["Payload"])
    assert "matchId" in payload
    assert payload["round"] == 12


def test_orchestrator_continues_when_team_sheet_unavailable(
    aws_env, ddb_and_s3, draw_data
):
    """Team sheets may not be available yet (e.g. early in the week);
    orchestrator must still trigger the agent — agent will use cached/stale
    team sheet data or fail per-match without blocking the whole round."""
    from orchestrator.lambda_handler import lambda_handler

    lambda_mock = MagicMock()
    with patch("orchestrator.lambda_handler.fetch_draw", return_value=draw_data), \
         patch("orchestrator.lambda_handler.fetch_team_sheet_page",
               side_effect=TeamSheetNotFound("not posted yet")), \
         patch("orchestrator.lambda_handler.boto3.client", return_value=lambda_mock):
        result = lambda_handler({"season": 2026, "round": 12}, {})

    # All matches still trigger agent invocations
    assert len(result["agent_triggered"]) == 3


def test_orchestrator_staggers_agent_invocations(ddb_and_s3, draw_data, monkeypatch):
    """Anthropic enforces 50K input tokens/min; firing all agent invokes at once
    blows past that. The orchestrator sleeps between invokes when the stagger
    env var is set."""
    monkeypatch.setenv("TEAMS_TABLE", "teams")
    monkeypatch.setenv("RAW_BUCKET", "test-bucket")
    monkeypatch.setenv("AGENT_FUNCTION_NAME", "nrl-predictor-agent")
    monkeypatch.setenv("AGENT_INVOKE_STAGGER_SECONDS", "8")

    from orchestrator.lambda_handler import lambda_handler

    sleep_mock = MagicMock()
    with patch("orchestrator.lambda_handler.fetch_draw", return_value=draw_data), \
         patch("orchestrator.lambda_handler.fetch_team_sheet_page", side_effect=TeamSheetNotFound("skip")), \
         patch("orchestrator.lambda_handler.boto3.client"), \
         patch("orchestrator.lambda_handler.time.sleep", sleep_mock):
        lambda_handler({"season": 2026, "round": 12}, {})

    # 3 invocations → 2 sleeps (no sleep before the first one)
    assert sleep_mock.call_count == 2
    assert sleep_mock.call_args_list[0].args == (8.0,)


def test_orchestrator_writes_teams_entries_to_dynamo(aws_env, ddb_and_s3, draw_data):
    from orchestrator.lambda_handler import lambda_handler

    with patch("orchestrator.lambda_handler.fetch_draw", return_value=draw_data), \
         patch("orchestrator.lambda_handler.fetch_team_sheet_page", side_effect=TeamSheetNotFound("skip")), \
         patch("orchestrator.lambda_handler.boto3.client"):
        lambda_handler({"season": 2026, "round": 12}, {})

    table = boto3.resource("dynamodb", region_name="ap-southeast-2").Table("teams")
    items = table.scan()["Items"]
    # 3 fixtures × 2 sides
    assert len([i for i in items if i.get("matchId", "").startswith("round-12-")]) == 6
