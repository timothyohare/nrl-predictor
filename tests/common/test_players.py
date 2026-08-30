"""Tests for common/players.py — injury-mention matching for the stats-elo-v1
injury signal (docs/plans/11-team-sheet-injury-weather-signals.md, Phase 3).
"""
import boto3
import pytest
from moto import mock_aws

from common.players import (
    has_spine_player_ruled_out,
    injury_adjustment,
    latest_status,
    player_slug,
    spine_player_slugs,
)


def test_player_slug_matches_articles_scraper_normalization():
    # Same normalization as scrapers/articles/lambda_handler.py::_player_slug —
    # a team-sheet full name and an injuries-table pk must be directly
    # comparable without any fuzzy matching.
    assert player_slug("Tanah Boyd") == "tanah-boyd"
    assert player_slug("O'Brien Smith") == "o-brien-smith"


def _sheet(home_players, away_players=None):
    return {"homePlayers": home_players, "awayPlayers": away_players or []}


def _player(number, first, last):
    return {"jersey_number": number, "first_name": first, "last_name": last}


def test_spine_player_slugs_only_includes_spine_jerseys():
    sheet = _sheet([
        _player(1, "Will", "Kennedy"),
        _player(2, "Sione", "Katoa"),  # winger — not spine
        _player(7, "Nicho", "Hynes"),
    ])
    slugs = spine_player_slugs(sheet, "homePlayers")
    assert slugs == {1: "will-kennedy", 7: "nicho-hynes"}


@pytest.fixture
def injuries_table():
    with mock_aws():
        client = boto3.client("dynamodb", region_name="ap-southeast-2")
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
        yield boto3.resource("dynamodb", region_name="ap-southeast-2").Table("injuries")


def _mention(table, team, player, status, scraped_at):
    table.put_item(Item={
        "pk": f"injury#{team}#{player_slug(player)}",
        "sk": scraped_at,
        "player": player,
        "team": team,
        "status": status,
        "detail": "",
    })


class TestLatestStatus:
    def test_no_mention_returns_none(self, injuries_table):
        assert latest_status(injuries_table, "warriors", "tanah-boyd") is None

    def test_returns_most_recent_mention(self, injuries_table):
        _mention(injuries_table, "warriors", "Tanah Boyd", "doubtful", "2026-08-20T00:00:00Z")
        _mention(injuries_table, "warriors", "Tanah Boyd", "out", "2026-08-22T00:00:00Z")
        assert latest_status(injuries_table, "warriors", "tanah-boyd") == "out"

    def test_a_later_available_mention_overrides_an_earlier_out(self, injuries_table):
        _mention(injuries_table, "warriors", "Tanah Boyd", "out", "2026-08-20T00:00:00Z")
        _mention(injuries_table, "warriors", "Tanah Boyd", "available", "2026-08-24T00:00:00Z")
        assert latest_status(injuries_table, "warriors", "tanah-boyd") == "available"

    def test_ignores_mentions_after_the_before_cutoff(self, injuries_table):
        _mention(injuries_table, "warriors", "Tanah Boyd", "out", "2026-08-20T00:00:00Z")
        _mention(injuries_table, "warriors", "Tanah Boyd", "available", "2026-08-24T00:00:00Z")
        assert latest_status(
            injuries_table, "warriors", "tanah-boyd", before="2026-08-22T00:00:00Z"
        ) == "out"


class TestHasSpinePlayerRuledOut:
    def test_true_when_a_named_spine_player_is_out(self, injuries_table):
        sheet = _sheet([_player(7, "Nicho", "Hynes")])
        _mention(injuries_table, "sharks", "Nicho Hynes", "out", "2026-08-20T00:00:00Z")
        assert has_spine_player_ruled_out(sheet, "homePlayers", "sharks", injuries_table) is True

    def test_false_when_no_mention_exists(self, injuries_table):
        sheet = _sheet([_player(7, "Nicho", "Hynes")])
        assert has_spine_player_ruled_out(sheet, "homePlayers", "sharks", injuries_table) is False

    def test_false_when_most_recent_mention_is_available(self, injuries_table):
        sheet = _sheet([_player(7, "Nicho", "Hynes")])
        _mention(injuries_table, "sharks", "Nicho Hynes", "out", "2026-08-20T00:00:00Z")
        _mention(injuries_table, "sharks", "Nicho Hynes", "returning", "2026-08-24T00:00:00Z")
        assert has_spine_player_ruled_out(sheet, "homePlayers", "sharks", injuries_table) is False

    def test_false_when_injuries_table_is_none(self):
        sheet = _sheet([_player(7, "Nicho", "Hynes")])
        assert has_spine_player_ruled_out(sheet, "homePlayers", "sharks", None) is False


def test_injury_adjustment_is_inert_by_default():
    assert injury_adjustment(False) == 0.0
    assert injury_adjustment(True) < 0.0
