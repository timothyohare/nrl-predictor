"""Target-week rule (spec Phase 3): which games the daily run should predict."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from common.nfl.games import Game
from common.nfl.match_id import match_id
from nfl.orchestrator.target_week import CANCELLED_AFTER, select_target

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)


def game(season, week, home, away, *, score=None, kickoff=None, stage="REG"):
    home_score, away_score = score if score else (None, None)
    return Game(
        game_id=f"{season}_{week:02d}_{away}_{home}",
        match_id=match_id(season, week, home, away),
        season=season,
        week=week,
        stage=stage,
        home=home,
        away=away,
        home_score=home_score,
        away_score=away_score,
        neutral=False,
        kickoff_utc=kickoff,
    )


def ago(hours: float) -> datetime:
    return NOW - timedelta(hours=hours)


def ahead(hours: float) -> datetime:
    return NOW + timedelta(hours=hours)


def ids(games):
    return {g.match_id for g in games}


def test_cancelled_threshold_is_72_hours():
    assert timedelta(hours=72) == CANCELLED_AFTER


def test_target_is_the_lowest_week_with_a_future_game_in_the_latest_season():
    games = [
        game(2025, 18, "chiefs", "raiders", score=(20, 10), kickoff=ago(24 * 300)),
        game(2026, 7, "bears", "patriots", score=(30, 24), kickoff=ago(100)),
        game(2026, 8, "packers", "panthers", kickoff=ahead(36)),
        game(2026, 8, "broncos", "chiefs", kickoff=ahead(100)),
        game(2026, 9, "ravens", "jaguars", kickoff=ahead(200)),
    ]
    target = select_target(games, NOW)
    assert (target.season, target.week) == (2026, 8)
    assert ids(target.to_predict) == {
        "nfl-2026-week-8-packers-v-panthers", "nfl-2026-week-8-broncos-v-chiefs",
    }
    assert target.blockers == [] and target.cancelled == []


def test_season_is_derived_from_the_data_not_the_calendar():
    games = [game(2027, 1, "chiefs", "ravens", kickoff=ahead(10))]
    games.append(game(2026, 1, "bears", "packers", kickoff=ahead(5)))
    target = select_target(games, NOW)
    assert (target.season, target.week) == (2027, 1)


def test_unscored_earlier_game_inside_72h_blocks_the_week():
    stuck = game(2026, 7, "ravens", "bengals", kickoff=ago(43))
    games = [stuck, game(2026, 8, "packers", "panthers", kickoff=ahead(36))]
    target = select_target(games, NOW)
    assert target.week == 8
    assert target.blockers == [stuck]
    assert target.to_predict == []
    assert target.cancelled == []


def test_unscored_earlier_game_past_72h_is_treated_as_cancelled():
    stuck = game(2026, 7, "ravens", "bengals", kickoff=ago(73))
    games = [stuck, game(2026, 8, "packers", "panthers", kickoff=ahead(36))]
    target = select_target(games, NOW)
    assert target.cancelled == [stuck]
    assert target.blockers == []
    assert ids(target.to_predict) == {"nfl-2026-week-8-packers-v-panthers"}


def test_exactly_72h_is_still_blocking():
    stuck = game(2026, 7, "ravens", "bengals", kickoff=ago(72))
    target = select_target([stuck, game(2026, 8, "packers", "panthers", kickoff=ahead(1))], NOW)
    assert target.blockers == [stuck]


def test_unscored_earlier_game_without_kickoff_blocks():
    stuck = game(2026, 7, "ravens", "bengals", kickoff=None)
    target = select_target([stuck, game(2026, 8, "packers", "panthers", kickoff=ahead(1))], NOW)
    assert target.blockers == [stuck]


def test_kicked_off_target_week_game_is_neither_predicted_nor_blocking():
    thursday = game(2026, 8, "packers", "panthers", kickoff=ago(2))
    sunday = game(2026, 8, "broncos", "chiefs", kickoff=ahead(60))
    target = select_target([thursday, sunday], NOW)
    assert target.week == 8
    assert target.to_predict == [sunday]
    assert target.blockers == []


def test_kickoff_exactly_now_is_not_predicted():
    on_the_whistle = game(2026, 8, "packers", "panthers", kickoff=NOW)
    later = game(2026, 8, "broncos", "chiefs", kickoff=ahead(1))
    assert select_target([on_the_whistle, later], NOW).to_predict == [later]


def test_no_future_games_means_nothing_to_predict():
    """Week 18 finished and no Wild Card rows published yet (or season over)."""
    games = [game(2026, 18, "chiefs", "raiders", score=(27, 3), kickoff=ago(30))]
    target = select_target(games, NOW)
    assert target.season == 2026
    assert target.week is None
    assert target.to_predict == [] and target.blockers == [] and target.cancelled == []


def test_empty_input():
    target = select_target([], NOW)
    assert (target.season, target.week, target.to_predict) == (None, None, [])


def test_to_predict_is_ordered_by_kickoff_then_match_id():
    late = game(2026, 8, "broncos", "chiefs", kickoff=ahead(100))
    early_b = game(2026, 8, "jets", "raiders", kickoff=ahead(50))
    early_a = game(2026, 8, "bills", "dolphins", kickoff=ahead(50))
    assert select_target([late, early_b, early_a], NOW).to_predict == [early_a, early_b, late]
