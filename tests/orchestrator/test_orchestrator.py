import json
from pathlib import Path
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

from scrapers.nrl.team_sheet import TeamSheetNotFound

FIXTURE = Path(__file__).parent.parent / "fixtures" / "nrl_draw_round12.json"
FINALS_FIXTURE = Path(__file__).parent.parent / "fixtures" / "nrl_draw_finals_week1.json"


@pytest.fixture
def draw_data():
    return json.loads(FIXTURE.read_text())


@pytest.fixture
def finals_draw_data():
    return json.loads(FINALS_FIXTURE.read_text())


@pytest.fixture
def aws_env(monkeypatch):
    monkeypatch.setenv("TEAMS_TABLE", "teams")
    monkeypatch.setenv("RAW_BUCKET", "test-bucket")
    monkeypatch.setenv("PREDICTIONS_TABLE", "predictions")
    monkeypatch.setenv("RESULTS_TABLE", "results")
    monkeypatch.setenv("INJURIES_TABLE", "injuries")
    monkeypatch.setenv("WEATHER_TABLE", "weather")


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
        client.create_table(
            TableName="injuries",
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        client.create_table(
            TableName="weather",
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        boto3.client("s3", region_name="ap-southeast-2").create_bucket(
            Bucket="test-bucket",
            CreateBucketConfiguration={"LocationConstraint": "ap-southeast-2"},
        )
        yield


def test_orchestrator_predicts_every_match(aws_env, ddb_and_s3, draw_data):
    from v1.orchestrator.lambda_handler import lambda_handler

    with patch("v1.orchestrator.lambda_handler.fetch_draw", return_value=draw_data), \
         patch("v1.orchestrator.lambda_handler.fetch_team_sheet_page", side_effect=TeamSheetNotFound("skip in test")):
        result = lambda_handler({"season": 2026, "round": 12}, {})

    # 3 fixtures have matchCentreUrl
    assert result["matches"] == 3
    assert len(result["predicted"]) == 3
    assert "round-12-panthers-v-broncos" in result["predicted"]

    predictions_table = boto3.resource("dynamodb", region_name="ap-southeast-2").Table("predictions")
    items = predictions_table.scan()["Items"]
    assert len(items) == 3
    for item in items:
        assert item["status"] == "OK"
        assert item["model_used"] == "stats-elo-v1"
        assert item["roundNumber"] == 12


def test_orchestrator_predicts_finals_matches(aws_env, ddb_and_s3, finals_draw_data):
    from v1.orchestrator.lambda_handler import lambda_handler

    with patch("v1.orchestrator.lambda_handler.fetch_draw", return_value=finals_draw_data), \
         patch("v1.orchestrator.lambda_handler.fetch_team_sheet_page", side_effect=TeamSheetNotFound("skip in test")):
        result = lambda_handler({"season": 2026, "round": 28}, {})

    assert result["round"] == 28
    assert len(result["predicted"]) == result["matches"]


def test_orchestrator_continues_when_team_sheet_unavailable(aws_env, ddb_and_s3, draw_data):
    """Team sheets may not be available yet (e.g. early in the week);
    orchestrator must still predict every match."""
    from v1.orchestrator.lambda_handler import lambda_handler

    with patch("v1.orchestrator.lambda_handler.fetch_draw", return_value=draw_data), \
         patch("v1.orchestrator.lambda_handler.fetch_team_sheet_page",
               side_effect=TeamSheetNotFound("not posted yet")):
        result = lambda_handler({"season": 2026, "round": 12}, {})

    assert len(result["predicted"]) == 3


def test_orchestrator_writes_team_sheet_under_slug(aws_env, ddb_and_s3, draw_data):
    """The team sheet row must be keyed by the round-qualified slug (the same id
    the API/agent tooling queries by), not the numerical q-data matchId.
    """
    from v1.agent.tools.team_sheet import get_team_sheet
    from v1.orchestrator.lambda_handler import lambda_handler

    q_data = json.loads(
        (Path(__file__).parent.parent / "fixtures" / "nrl_team_sheet_qdata.json").read_text()
    )

    with patch("v1.orchestrator.lambda_handler.fetch_draw", return_value=draw_data), \
         patch("v1.orchestrator.lambda_handler.fetch_team_sheet_page", return_value=q_data):
        lambda_handler({"season": 2026, "round": 12}, {})

    table = boto3.resource("dynamodb", region_name="ap-southeast-2").Table("teams")
    # Readable via the agent tool by slug; the numerical key must be absent.
    sheet = get_team_sheet("round-12-panthers-v-broncos", round_number=12, table=table)
    assert "homePlayers" in sheet
    assert "Item" not in table.get_item(Key={"teamId": "20261111110", "round": "12"})


def test_orchestrator_writes_teams_entries_to_dynamo(aws_env, ddb_and_s3, draw_data):
    from v1.orchestrator.lambda_handler import lambda_handler

    with patch("v1.orchestrator.lambda_handler.fetch_draw", return_value=draw_data), \
         patch("v1.orchestrator.lambda_handler.fetch_team_sheet_page", side_effect=TeamSheetNotFound("skip")):
        lambda_handler({"season": 2026, "round": 12}, {})

    table = boto3.resource("dynamodb", region_name="ap-southeast-2").Table("teams")
    items = table.scan()["Items"]
    # 3 fixtures × 2 sides
    assert len([i for i in items if i.get("matchId", "").startswith("round-12-")]) == 6


def test_first_ever_scrape_of_a_round_flags_no_spine_change(aws_env, ddb_and_s3, draw_data):
    """No prior team sheet to diff against — never a change (docs/plans/11)."""
    from v1.orchestrator.lambda_handler import lambda_handler

    q_data = json.loads(
        (Path(__file__).parent.parent / "fixtures" / "nrl_team_sheet_qdata.json").read_text()
    )

    with patch("v1.orchestrator.lambda_handler.fetch_draw", return_value=draw_data), \
         patch("v1.orchestrator.lambda_handler.fetch_team_sheet_page", return_value=q_data):
        lambda_handler({"season": 2026, "round": 12}, {})

    table = boto3.resource("dynamodb", region_name="ap-southeast-2").Table("teams")
    item = table.get_item(Key={"teamId": "round-12-panthers-v-broncos", "round": "12"})["Item"]
    assert item["spine_changed_home"] is False
    assert item["spine_changed_away"] is False
    assert item["changed_positions"] == []


def test_second_scrape_with_a_different_fullback_flags_home_spine_change(aws_env, ddb_and_s3, draw_data):
    from v1.orchestrator.lambda_handler import lambda_handler

    q_data = json.loads(
        (Path(__file__).parent.parent / "fixtures" / "nrl_team_sheet_qdata.json").read_text()
    )

    with patch("v1.orchestrator.lambda_handler.fetch_draw", return_value=draw_data), \
         patch("v1.orchestrator.lambda_handler.fetch_team_sheet_page", return_value=q_data):
        lambda_handler({"season": 2026, "round": 12}, {})  # first scrape, no prior item

        changed_q_data = json.loads(json.dumps(q_data))  # deep copy
        changed_q_data["match"]["homeTeam"]["players"][0]["firstName"] = "Replacement"
        with patch("v1.orchestrator.lambda_handler.fetch_team_sheet_page", return_value=changed_q_data):
            lambda_handler({"season": 2026, "round": 12}, {})  # second scrape, fullback swapped

    table = boto3.resource("dynamodb", region_name="ap-southeast-2").Table("teams")
    item = table.get_item(Key={"teamId": "round-12-panthers-v-broncos", "round": "12"})["Item"]
    assert item["spine_changed_home"] is True
    assert item["spine_changed_away"] is False
    assert item["changed_positions"] == [1]
