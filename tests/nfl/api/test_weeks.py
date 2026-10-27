"""GET /nfl/weeks/current (spec Phase 4, criterion 4.7): the Phase 3 target-week
rule over nfl_games; after the Super Bowl (or before playoff rows exist) the last
week played."""
from __future__ import annotations

from datetime import datetime

import pytest

from nfl.api import weeks as handler
from tests.nfl.api.conftest import body, event, game, put

NOW = "2026-10-28T12:00:00+00:00"


@pytest.fixture
def freeze(monkeypatch):
    def _freeze(iso: str) -> None:
        monkeypatch.setattr(handler, "_now", lambda: datetime.fromisoformat(iso))
    return _freeze


def get() -> dict:
    return handler.lambda_handler(event("/nfl/weeks/current"), None)


def week_7_and_8(*, mnf_score: tuple[int, int] | None = (20, 17),
                 mnf_kickoff: str = "2026-10-27T00:15:00Z") -> list[dict]:
    return [
        game("nfl-2026-week-7-bears-v-patriots", kickoff="2026-10-23T00:15:00Z", score=(30, 24)),
        game("nfl-2026-week-7-cowboys-v-eagles", kickoff=mnf_kickoff, score=mnf_score),
        game("nfl-2026-week-8-packers-v-panthers", kickoff="2026-10-30T00:15:00Z"),
        game("nfl-2026-week-8-broncos-v-chiefs", kickoff="2026-11-01T21:25:00Z"),
    ]


def test_next_week_once_the_previous_one_is_final(tables, freeze):
    freeze(NOW)
    put(tables.games, *week_7_and_8())
    response = get()
    assert response["statusCode"] == 200
    assert response["headers"]["Content-Type"] == "application/json"
    assert body(response) == {"season": 2026, "week": 8, "stage": "REG", "label": "Week 8"}


def test_week_7_with_one_game_still_to_play_is_current(tables, freeze):
    freeze(NOW)
    put(tables.games, *week_7_and_8(mnf_score=None, mnf_kickoff="2026-10-29T00:15:00Z"))
    assert body(get())["week"] == 7


def test_week_7_game_awaiting_its_result_still_targets_week_8(tables, freeze):
    """Kicked off, unscored, inside 72h: the target week is 8 (blocked, not 7)."""
    freeze(NOW)
    put(tables.games, *week_7_and_8(mnf_score=None))
    assert body(get())["week"] == 8


def test_latest_season_wins(tables, freeze):
    freeze(NOW)
    put(tables.games, *week_7_and_8(),
        game("nfl-2025-week-22-chiefs-v-eagles", stage="SB", kickoff="2026-02-08T23:30:00Z",
             score=(20, 27)))
    assert body(get())["season"] == 2026


def test_playoff_week_label_comes_from_the_stage(tables, freeze):
    freeze("2026-01-08T12:00:00+00:00")
    put(tables.games,
        game("nfl-2025-week-18-bills-v-jets", kickoff="2026-01-04T18:00:00Z", score=(30, 10)),
        game("nfl-2025-week-19-bills-v-dolphins", stage="WC", kickoff="2026-01-10T21:30:00Z"))
    assert body(get()) == {"season": 2025, "week": 19, "stage": "WC", "label": "Wild Card"}


def test_after_the_super_bowl_returns_the_last_week_played(tables, freeze):
    freeze("2026-03-01T12:00:00+00:00")
    put(tables.games,
        game("nfl-2025-week-21-bills-v-chiefs", stage="CON", kickoff="2026-01-25T20:00:00Z",
             score=(24, 27)),
        game("nfl-2025-week-22-chiefs-v-eagles", stage="SB", kickoff="2026-02-08T23:30:00Z",
             score=(20, 27)))
    assert body(get()) == {"season": 2025, "week": 22, "stage": "SB", "label": "Super Bowl"}


def test_week_18_done_before_wild_card_rows_exist(tables, freeze):
    freeze("2026-01-05T12:00:00+00:00")
    put(tables.games,
        game("nfl-2025-week-17-bills-v-jets", kickoff="2025-12-28T18:00:00Z", score=(30, 10)),
        game("nfl-2025-week-18-bills-v-dolphins", kickoff="2026-01-04T18:00:00Z", score=(21, 14)))
    assert body(get()) == {"season": 2025, "week": 18, "stage": "REG", "label": "Week 18"}


def test_no_games_is_404(tables, freeze):
    freeze(NOW)
    response = get()
    assert response["statusCode"] == 404
    assert "error" in body(response)


def test_real_clock_is_utc_aware():
    now = handler._now()
    assert now.tzinfo is not None and now.utcoffset().total_seconds() == 0


# --- GET /nfl/weeks?season= (Phase 5 week selector labels) ---------------------

def list_weeks(query: dict | None = None) -> dict:
    return handler.list_handler(event("/nfl/weeks", query=query), None)


def playoff_season() -> list[dict]:
    return [
        game("nfl-2025-week-18-bills-v-jets", kickoff="2026-01-04T18:00:00Z", score=(30, 10)),
        game("nfl-2025-week-18-chiefs-v-raiders", kickoff="2026-01-04T21:25:00Z", score=(20, 3)),
        game("nfl-2025-week-19-bills-v-dolphins", stage="WC", kickoff="2026-01-10T21:30:00Z"),
        game("nfl-2025-week-1-bills-v-ravens", kickoff="2025-09-08T00:20:00Z", score=(41, 40)),
        game("nfl-2026-week-1-eagles-v-cowboys", kickoff="2026-09-11T00:20:00Z"),
    ]


def test_weeks_list_labels_come_from_the_stage(tables):
    put(tables.games, *playoff_season())
    response = list_weeks({"season": "2025"})
    assert response["statusCode"] == 200
    assert response["headers"]["Content-Type"] == "application/json"
    assert body(response) == {"season": 2025, "weeks": [
        {"week": 1, "stage": "REG", "label": "Week 1"},
        {"week": 18, "stage": "REG", "label": "Week 18"},
        {"week": 19, "stage": "WC", "label": "Wild Card"},
    ]}


def test_weeks_list_defaults_to_the_latest_season(tables):
    put(tables.games, *playoff_season())
    assert body(list_weeks()) == {"season": 2026, "weeks": [
        {"week": 1, "stage": "REG", "label": "Week 1"}]}


def test_weeks_list_2020_wild_card_is_week_18(tables):
    put(tables.games,
        game("nfl-2020-week-17-bills-v-dolphins", kickoff="2021-01-03T18:00:00Z", score=(56, 26)),
        game("nfl-2020-week-18-bills-v-colts", stage="WC", kickoff="2021-01-09T18:05:00Z",
             score=(27, 24)))
    assert [w["label"] for w in body(list_weeks({"season": "2020"}))["weeks"]] == [
        "Week 17", "Wild Card"]


@pytest.mark.parametrize("season", ["abc", "1800", ""])
def test_weeks_list_bad_season_is_400(tables, season):
    response = list_weeks({"season": season})
    assert response["statusCode"] == 400
    assert "error" in body(response)


def test_weeks_list_unknown_season_is_404(tables):
    put(tables.games, *playoff_season())
    assert list_weeks({"season": "2019"})["statusCode"] == 404


def test_weeks_list_no_games_is_404(tables):
    assert list_weeks()["statusCode"] == 404
