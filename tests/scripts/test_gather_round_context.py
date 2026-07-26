"""Tests for scripts/gather_round_context.py — deterministic per-match data
gathering (no Anthropic API calls), match_context DynamoDB writes, and
paste-ready prompt file rendering for manual use in Claude Pro."""
from datetime import UTC, datetime

import boto3
import pytest
from moto import mock_aws

from scrapers.shared.models import Match
from scripts.gather_round_context import (
    build_context_row,
    gather_match_data,
    gather_round,
    render_prompt,
    write_prompt_file,
)

REGION = "ap-southeast-2"


@pytest.fixture
def ddb():
    with mock_aws():
        resource = boto3.resource("dynamodb", region_name=REGION)
        resource.create_table(
            TableName="teams",
            KeySchema=[{"AttributeName": "teamId", "KeyType": "HASH"},
                       {"AttributeName": "round", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "teamId", "AttributeType": "S"},
                                  {"AttributeName": "round", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        resource.create_table(
            TableName="results",
            KeySchema=[{"AttributeName": "matchId", "KeyType": "HASH"},
                       {"AttributeName": "scoredAt", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "matchId", "AttributeType": "S"},
                                  {"AttributeName": "scoredAt", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        resource.create_table(
            TableName="injuries",
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"},
                       {"AttributeName": "sk", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"},
                                  {"AttributeName": "sk", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        resource.create_table(
            TableName="weather",
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"},
                       {"AttributeName": "sk", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"},
                                  {"AttributeName": "sk", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        resource.create_table(
            TableName="retrospectives",
            KeySchema=[{"AttributeName": "matchId", "KeyType": "HASH"},
                       {"AttributeName": "generatedAt", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "matchId", "AttributeType": "S"},
                                  {"AttributeName": "generatedAt", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        resource.create_table(
            TableName="match_context",
            KeySchema=[{"AttributeName": "matchId", "KeyType": "HASH"},
                       {"AttributeName": "generatedAt", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "matchId", "AttributeType": "S"},
                                  {"AttributeName": "generatedAt", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        yield resource


@pytest.fixture
def match():
    return Match(
        match_id="round-11-panthers-v-broncos",
        home_team="panthers",
        away_team="broncos",
        venue="BlueBet Stadium",
        round_number=11,
        kick_off="2026-05-16T09:50:00Z",
        match_state="Pre",
    )


def _seed_team_sheet(ddb, match_id, round_number):
    ddb.Table("teams").put_item(Item={
        "teamId": match_id, "round": str(round_number),
        "homeTeam": "Panthers", "awayTeam": "Broncos",
        "homePlayers": [], "awayPlayers": [],
        "matchState": "Pre", "kickOff": "2026-05-16T09:50:00Z",
        "scraped_at": datetime.now(UTC).isoformat(),
    })


def _tool_tables(ddb):
    return {
        "teams_table": ddb.Table("teams"),
        "results_table": ddb.Table("results"),
        "injuries_table": ddb.Table("injuries"),
        "weather_table": ddb.Table("weather"),
        "retro_table": ddb.Table("retrospectives"),
    }


def test_gather_match_data_assembles_all_tool_outputs(ddb, match):
    _seed_team_sheet(ddb, match.match_id, match.round_number)
    data = gather_match_data(match, season=2026, **_tool_tables(ddb))

    expected_keys = {
        "team_sheet", "injuries", "recent_form", "head_to_head", "weather",
        "ladder", "fantasy_stats", "venue_profile", "lessons",
        "coaching_matchup", "trap_game", "spine_synergy",
    }
    assert expected_keys <= data.keys()
    assert data["team_sheet"]["homeTeam"] == "Panthers"
    assert set(data["injuries"].keys()) == {"home", "away"}
    assert set(data["recent_form"].keys()) == {"home", "away"}
    assert set(data["fantasy_stats"].keys()) == {"home", "away"}
    # get_recent_form's momentum calc returns native floats on an empty
    # results table — exercises the Decimal conversion needed before any
    # DynamoDB write, without needing extra seed data.
    assert isinstance(data["recent_form"]["home"]["momentum"]["weighted_win_rate"], float)


def test_gather_match_data_isolates_tool_failures(ddb, match):
    # Team sheet deliberately not seeded -> get_team_sheet raises ToolError.
    # Every other tool call must still succeed independently.
    data = gather_match_data(match, season=2026, **_tool_tables(ddb))

    assert "error" in data["team_sheet"]
    assert "error" not in data["venue_profile"]  # static lookup, unaffected
    assert "error" not in data["ladder"]


def test_gather_match_data_handles_missing_kickoff(ddb):
    no_kickoff = Match(
        match_id="round-11-eels-v-storm", home_team="eels", away_team="storm",
        venue="CommBank Stadium", round_number=11, kick_off=None, match_state="Pre",
    )
    data = gather_match_data(no_kickoff, season=2026, **_tool_tables(ddb))
    assert "error" in data["weather"]


def test_build_context_row_shape(match):
    data = {"team_sheet": {"homeTeam": "Panthers"}}
    row = build_context_row(match, season=2026, data=data, generated_at="2026-05-01T00:00:00+00:00")

    assert row["matchId"] == match.match_id
    assert row["generatedAt"] == "2026-05-01T00:00:00+00:00"
    assert row["scraped_at"] == "2026-05-01T00:00:00+00:00"
    assert row["roundNumber"] == 11
    assert row["homeTeam"] == "panthers"
    assert row["awayTeam"] == "broncos"
    assert row["data"] == data
    assert "promptVersion" in row


def test_render_prompt_contains_both_sections_and_data(match):
    row = build_context_row(
        match, season=2026, data={"team_sheet": {"homeTeam": "Panthers"}},
        generated_at="2026-05-01T00:00:00+00:00",
    )
    text = render_prompt(row)

    assert "SYSTEM PROMPT" in text
    assert "USER MESSAGE" in text
    assert match.match_id in text
    assert '"homeTeam": "Panthers"' in text
    assert "do not ask for more data" in text.lower()


def test_write_prompt_file_writes_expected_path(tmp_path, match):
    row = build_context_row(match, season=2026, data={"team_sheet": {}}, generated_at="now")
    path = write_prompt_file(tmp_path, row, "content")

    assert path == tmp_path / "2026" / "round-11" / f"{match.match_id}.md"
    assert path.read_text() == "content"


def test_gather_round_dry_run_skips_all_writes(ddb, match, tmp_path):
    rows = gather_round(
        [match], season=2026, **_tool_tables(ddb),
        context_table=ddb.Table("match_context"),
        output_dir=tmp_path,
        dry_run=True,
    )

    assert len(rows) == 1
    assert ddb.Table("match_context").scan()["Items"] == []
    assert list(tmp_path.iterdir()) == []


def test_gather_round_writes_context_table_and_prompt_file(ddb, match, tmp_path):
    _seed_team_sheet(ddb, match.match_id, match.round_number)
    rows = gather_round(
        [match], season=2026, **_tool_tables(ddb),
        context_table=ddb.Table("match_context"),
        output_dir=tmp_path,
        dry_run=False,
    )

    assert len(rows) == 1
    items = ddb.Table("match_context").scan()["Items"]
    assert len(items) == 1
    assert items[0]["matchId"] == match.match_id
    assert items[0]["roundNumber"] == 11

    prompt_path = tmp_path / "2026" / "round-11" / f"{match.match_id}.md"
    assert prompt_path.exists()
    assert "SYSTEM PROMPT" in prompt_path.read_text()


class _FailingTable:
    """Stand-in for a match_context table that hasn't been deployed yet."""

    def put_item(self, Item):  # noqa: N803 - matches boto3's put_item(Item=...) signature
        raise RuntimeError("ResourceNotFoundException: table does not exist")


def test_gather_round_writes_prompt_file_even_if_context_table_write_fails(ddb, match, tmp_path):
    rows = gather_round(
        [match], season=2026, **_tool_tables(ddb),
        context_table=_FailingTable(),
        output_dir=tmp_path,
        dry_run=False,
    )

    assert len(rows) == 1
    prompt_path = tmp_path / "2026" / "round-11" / f"{match.match_id}.md"
    assert prompt_path.exists()
    assert "SYSTEM PROMPT" in prompt_path.read_text()


def test_gather_round_continues_after_one_match_fully_errors(ddb, tmp_path):
    good = Match(
        match_id="round-11-panthers-v-broncos", home_team="panthers", away_team="broncos",
        venue="BlueBet Stadium", round_number=11, kick_off="2026-05-16T09:50:00Z", match_state="Pre",
    )
    _seed_team_sheet(ddb, good.match_id, good.round_number)
    other = Match(
        match_id="round-11-eels-v-storm", home_team="eels", away_team="storm",
        venue="CommBank Stadium", round_number=11, kick_off=None, match_state="Pre",
    )

    rows = gather_round(
        [good, other], season=2026, **_tool_tables(ddb),
        context_table=ddb.Table("match_context"),
        output_dir=tmp_path,
        dry_run=False,
    )

    assert [r["matchId"] for r in rows] == [good.match_id, other.match_id]
    assert len(ddb.Table("match_context").scan()["Items"]) == 2
