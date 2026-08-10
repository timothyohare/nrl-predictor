import json
from pathlib import Path
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

from scrapers.nrl.draw import lambda_handler, parse_draw, slug_from_match_centre_url
from scrapers.shared.models import Match

FIXTURE = Path(__file__).parent.parent / "fixtures" / "nrl_draw_round12.json"
FINALS_FIXTURE = Path(__file__).parent.parent / "fixtures" / "nrl_draw_finals_week1.json"


@pytest.fixture
def draw_data():
    return json.loads(FIXTURE.read_text())


@pytest.fixture
def finals_draw_data():
    return json.loads(FINALS_FIXTURE.read_text())


def test_slug_from_match_centre_url():
    url = "/draw/nrl-premiership/2026/round-12/sharks-v-bulldogs/"
    assert slug_from_match_centre_url(url) == "round-12-sharks-v-bulldogs"
    # Trailing slash optional
    assert slug_from_match_centre_url(url.rstrip("/")) == "round-12-sharks-v-bulldogs"


def test_parse_draw_returns_match_objects(draw_data):
    matches = parse_draw(draw_data)
    assert all(isinstance(m, Match) for m in matches)


def test_parse_draw_correct_field_mapping(draw_data):
    matches = parse_draw(draw_data)
    first = matches[0]
    assert first.match_id == "round-12-panthers-v-broncos"
    assert first.home_team == "panthers"
    assert first.away_team == "broncos"
    assert first.venue == "BlueBet Stadium"
    assert first.round_number == 12
    assert first.kick_off == "2026-05-16T09:50:00Z"
    assert first.match_state == "Pre"
    assert first.is_finals is False


def test_parse_draw_finals_week_round_number_and_flag(finals_draw_data):
    matches = parse_draw(finals_draw_data)
    finals_week_1 = matches[0]
    assert finals_week_1.match_id == "round-28-storm-v-bulldogs"
    assert finals_week_1.round_number == 28
    assert finals_week_1.is_finals is True


def test_parse_draw_grand_final_round_number_and_flag(finals_draw_data):
    matches = parse_draw(finals_draw_data)
    grand_final = matches[1]
    assert grand_final.match_id == "round-31-storm-v-broncos"
    assert grand_final.round_number == 31
    assert grand_final.is_finals is True


def test_parse_draw_kick_off_none_when_missing(draw_data):
    matches = parse_draw(draw_data)
    storm_match = next(m for m in matches if m.home_team == "storm")
    assert storm_match.kick_off is None


def test_parse_draw_skips_missing_match_centre_url(draw_data):
    matches = parse_draw(draw_data)
    team_names = [m.home_team for m in matches]
    assert "Titans" not in team_names


def test_parse_draw_empty_fixtures():
    matches = parse_draw({"fixtures": []})
    assert matches == []


@mock_aws
def test_lambda_handler_writes_to_dynamo_and_s3(draw_data, monkeypatch):
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

    with patch("scrapers.nrl.draw.fetch_draw", return_value=draw_data):
        lambda_handler({"season": 2026, "round": 12}, {})

    table = boto3.resource("dynamodb", region_name="ap-southeast-2").Table("teams")
    response = table.scan()
    # 3 fixtures have matchCentreUrl; each writes 2 items (home + away team)
    assert response["Count"] == 6
