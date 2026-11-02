"""Labelled walk-forward backfill (user decision Q2): 2026 weeks before the first
live week get `backfilled: true` predictions, never shadowing a live row and with
ratings strictly from earlier weeks."""
from __future__ import annotations

import random
from datetime import datetime

import pytest

from common.nfl.games import parse_csv
from common.nfl.model import NFL, predict_game
from common.stats_model.ratings import replay_ratings
from nfl.orchestrator.backfill import backfill
from nfl.orchestrator.lambda_handler import rng_seed
from tests.nfl.orchestrator.conftest import BEFORE_WEEK_8, FIXTURE_CSV, scan

NOW = datetime.fromisoformat(BEFORE_WEEK_8)
WEEK_5 = {"nfl-2026-week-5-commanders-v-giants"}
WEEK_7 = {
    "nfl-2026-week-7-bears-v-patriots",
    "nfl-2026-week-7-saints-v-steelers",
    "nfl-2026-week-7-ravens-v-bengals",
}
PREDICTED = ("predicted_winner", "predicted_margin", "margin_low", "margin_high",
             "home_win_probability", "confidence", "key_factors", "reasoning")


@pytest.fixture
def games():
    return parse_csv(FIXTURE_CSV.read_text())[0]


def live_row(match_id: str, week: int) -> dict:
    return {
        "matchId": match_id, "generatedAt": "2026-10-20T12:00:00+00:00", "season": 2026,
        "week": week, "status": "OK", "backfilled": False, "model_used": "nfl-elo-v1",
        "scraped_at": "2026-10-20T12:00:00+00:00",
    }


def test_backfills_every_earlier_week_labelled(tables, games):
    written = backfill(games, tables.predictions, NOW)
    rows = scan(tables.predictions)
    assert set(written) == WEEK_5 | WEEK_7
    assert {r["matchId"] for r in rows} == WEEK_5 | WEEK_7
    for row in rows:
        assert row["backfilled"] is True
        assert row["status"] == "OK"
        assert row["model_used"] == "nfl-elo-v1"
        assert row["season"] == 2026 and row["week"] in (5, 7)
        assert "scraped_at" in row and "kickoff_utc" in row


def test_backfill_uses_ratings_from_strictly_before_each_week(tables, games):
    backfill(games, tables.predictions, NOW)
    by_id = {g.match_id: g for g in games}
    for row in scan(tables.predictions):
        game = by_id[row["matchId"]]
        ratings = replay_ratings(games, NFL, before=(game.season, game.week))
        expected = predict_game(game, ratings, random.Random(rng_seed(game.match_id)))
        assert row["predicted_winner"] == expected.predicted_winner
        assert row["predicted_margin"] == expected.predicted_margin
        assert row["key_factors"] == expected.key_factors


@pytest.mark.parametrize("edited_week", [5, 7])
def test_changing_a_week_n_score_never_changes_backfill_up_to_week_n(tables, edited_week):
    text = FIXTURE_CSV.read_text()
    original = parse_csv(text)[0]
    backfill(original, tables.predictions, NOW)
    before = {r["matchId"]: tuple(r[k] for k in PREDICTED) for r in scan(tables.predictions)}
    for row in scan(tables.predictions):
        tables.predictions.delete_item(Key={"matchId": row["matchId"], "generatedAt": row["generatedAt"]})

    edited = [
        g if g.week != edited_week or g.season != 2026 else g.__class__(
            **{**g.__dict__, "home_score": 0, "away_score": 45}
        )
        for g in original
    ]
    backfill(edited, tables.predictions, NOW)
    after = {r["matchId"]: tuple(r[k] for k in PREDICTED) for r in scan(tables.predictions)}
    affected = WEEK_5 if edited_week == 5 else WEEK_5 | WEEK_7
    assert {m: after[m] for m in affected} == {m: before[m] for m in affected}


def test_default_stops_before_the_first_live_week(tables, games):
    tables.predictions.put_item(Item=live_row("nfl-2026-week-7-bears-v-patriots", 7))
    assert set(backfill(games, tables.predictions, NOW)) == WEEK_5


def test_never_shadows_a_live_prediction(tables, games):
    live = live_row("nfl-2026-week-7-bears-v-patriots", 7)
    tables.predictions.put_item(Item=live)
    written = backfill(games, tables.predictions, NOW, through_week=7)
    assert "nfl-2026-week-7-bears-v-patriots" not in written
    rows = [r for r in scan(tables.predictions) if r["matchId"] == live["matchId"]]
    assert rows == [live]


@pytest.mark.parametrize("through_week", [7, 9])
def test_explicit_through_week_is_capped_below_the_first_live_week(tables, games, through_week):
    """Review N5: the docstring's "only weeks before the first live week" holds for an
    explicit --through-week too, not just for the default."""
    tables.predictions.put_item(Item=live_row("nfl-2026-week-7-bears-v-patriots", 7))
    assert set(backfill(games, tables.predictions, NOW, through_week=through_week)) == WEEK_5
    assert {r["matchId"] for r in scan(tables.predictions)} == WEEK_5 | {
        "nfl-2026-week-7-bears-v-patriots"
    }


def test_a_backfilled_row_never_counts_as_the_first_live_week(tables, games):
    row = {**live_row("nfl-2026-week-7-bears-v-patriots", 7), "backfilled": True}
    tables.predictions.put_item(Item=row)
    assert set(backfill(games, tables.predictions, NOW, through_week=9)) == (
        WEEK_5 | WEEK_7 - {"nfl-2026-week-7-bears-v-patriots"}
    )


class _ScanRecorder:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def scan(self, **kwargs):
        self.calls.append(kwargs)
        return {"Items": []}


def test_first_live_week_lookup_is_a_consistent_read():
    """Review N1: the read that decides which weeks are safe to backfill is strongly
    consistent, so a live row written a moment ago is never missed."""
    from nfl.orchestrator.backfill import _first_live_week

    table = _ScanRecorder()
    assert _first_live_week(table, 2026) is None
    assert table.calls and all(c.get("ConsistentRead") is True for c in table.calls)


def test_rerun_is_idempotent(tables, games):
    backfill(games, tables.predictions, NOW)
    count = len(scan(tables.predictions))
    assert backfill(games, tables.predictions, NOW) == []
    assert len(scan(tables.predictions)) == count


def test_through_week_never_reaches_the_live_target_week(tables, games):
    written = backfill(games, tables.predictions, NOW, through_week=9)
    assert set(written) == WEEK_5 | WEEK_7


def test_dry_run_writes_nothing(tables, games):
    written = backfill(games, tables.predictions, NOW, dry_run=True)
    assert set(written) == WEEK_5 | WEEK_7
    assert scan(tables.predictions) == []


def test_after_the_season_backfills_every_week(tables, games):
    played_only = [g for g in games if not (g.season == 2026 and g.week >= 8)]
    assert set(backfill(played_only, tables.predictions, NOW)) == WEEK_5 | WEEK_7


def test_earlier_seasons_are_never_backfilled(tables, games):
    written = backfill(games, tables.predictions, NOW)
    assert all(m.startswith("nfl-2026-") for m in written)
