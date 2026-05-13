import json
import boto3
import pytest
from moto import mock_aws
from pathlib import Path
from unittest.mock import patch
from scrapers.nrl.team_sheet import parse_team_sheet, lambda_handler, TeamSheetNotFound
from scrapers.shared.models import TeamSheet, Player

FIXTURE = Path(__file__).parent.parent / "fixtures" / "nrl_team_sheet_qdata.json"


@pytest.fixture
def q_data():
    return json.loads(FIXTURE.read_text())


def test_parse_returns_team_sheet(q_data):
    ts = parse_team_sheet(q_data)
    assert isinstance(ts, TeamSheet)


def test_parse_match_id(q_data):
    ts = parse_team_sheet(q_data)
    assert ts.match_id == "20261111110"


def test_parse_kick_off(q_data):
    ts = parse_team_sheet(q_data)
    assert ts.kick_off == "2026-05-16T09:50:00Z"


def test_parse_match_state(q_data):
    ts = parse_team_sheet(q_data)
    assert ts.match_state == "Pre"


def test_parse_home_team_fields(q_data):
    ts = parse_team_sheet(q_data)
    assert ts.home_team.nick_name == "Sharks"
    assert ts.home_team.score is None
    assert len(ts.home_team.players) == 17


def test_parse_starting_vs_bench(q_data):
    ts = parse_team_sheet(q_data)
    starters = [p for p in ts.home_team.players if p.is_starting]
    bench = [p for p in ts.home_team.players if not p.is_starting]
    assert len(starters) == 13
    assert len(bench) == 4


def test_parse_player_fields(q_data):
    ts = parse_team_sheet(q_data)
    kennedy = ts.home_team.players[0]
    assert kennedy.first_name == "William"
    assert kennedy.last_name == "Kennedy"
    assert kennedy.jersey_number == 1
    assert kennedy.position == "Fullback"
    assert kennedy.is_starting is True
    assert kennedy.player_id == "P001"


def test_parse_raises_when_match_key_missing():
    with pytest.raises(TeamSheetNotFound):
        parse_team_sheet({})


def test_parse_raises_when_both_player_lists_empty():
    data = {"match": {"matchId": "x", "matchState": "Pre", "startTime": None, "roundNumber": 1,
                      "homeTeam": {"teamId": "1", "nickName": "A", "score": None, "players": []},
                      "awayTeam": {"teamId": "2", "nickName": "B", "score": None, "players": []}}}
    with pytest.raises(TeamSheetNotFound):
        parse_team_sheet(data)


@mock_aws
def test_lambda_handler_writes_to_dynamo_and_s3(q_data, monkeypatch):
    boto3.client("dynamodb", region_name="ap-southeast-2").create_table(
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
    monkeypatch.setenv("TEAMS_TABLE", "teams")
    monkeypatch.setenv("RAW_BUCKET", "test-bucket")

    fake_html = f'<div id="vue-match-centre" q-data=\'{json.dumps(q_data)}\'></div>'
    with patch("scrapers.nrl.team_sheet.fetch_team_sheet_page", return_value=q_data):
        lambda_handler({"matchCentreUrl": "/draw/nrl-premiership/2026/round-12/sharks-v-bulldogs/"}, {})

    table = boto3.resource("dynamodb", region_name="ap-southeast-2").Table("teams")
    item = table.get_item(Key={"teamId": "20261111110", "round": "12"})
    assert "Item" in item


@mock_aws
def test_lambda_handler_handles_not_found_gracefully(monkeypatch):
    monkeypatch.setenv("TEAMS_TABLE", "teams")
    monkeypatch.setenv("RAW_BUCKET", "test-bucket")
    with patch("scrapers.nrl.team_sheet.fetch_team_sheet_page", side_effect=TeamSheetNotFound("no data")):
        # should not raise
        lambda_handler({"matchCentreUrl": "/draw/nrl-premiership/2026/round-12/x-v-y/"}, {})
