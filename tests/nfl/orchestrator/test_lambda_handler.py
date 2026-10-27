"""NFL orchestrator Lambda (spec Phase 3, criteria 3.1-3.8) against moto."""
from __future__ import annotations

import logging
import random
import re
import urllib.error
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import boto3
import pytest

from common.nfl.games import parse_csv
from common.nfl.model import NFL, predict_game
from common.stats_model.ratings import replay_ratings
from nfl.orchestrator import lambda_handler as handler
from tests.nfl.orchestrator.conftest import (
    BEFORE_WEEK_8,
    FIXTURE_CSV,
    REGION,
    WEEK_8,
    scan,
    unscore,
)

PREDICTION_FIELDS = {
    "matchId", "generatedAt", "season", "week", "stage", "predicted_winner",
    "predicted_margin", "margin_low", "margin_high", "home_win_probability", "confidence",
    "key_factors", "reasoning", "model_used", "neutral", "kickoff_utc", "generation",
    "status", "scraped_at", "backfilled",
}
MARKET_PATTERN = re.compile(r"spread|moneyline|odds", re.IGNORECASE)


def run() -> dict:
    return handler.lambda_handler({}, None)


def unpredicted_metric_values() -> list[float]:
    cw = boto3.client("cloudwatch", region_name=REGION)
    now = datetime.now(UTC)
    stats = cw.get_metric_statistics(
        Namespace="NflPredictor",
        MetricName="UnpredictedGames",
        StartTime=now - timedelta(hours=1),
        EndTime=now + timedelta(hours=1),
        Period=60,
        Statistics=["Maximum"],
    )
    return [p["Maximum"] for p in stats["Datapoints"]]


def ok_rows(table) -> list[dict]:
    return [r for r in scan(table) if r["status"] == "OK"]


# --- 3.1 ---------------------------------------------------------------------------

def test_predicts_every_week_8_game_and_nothing_later(tables, freeze):
    freeze(BEFORE_WEEK_8)
    summary = run()
    rows = scan(tables.predictions)
    assert {r["matchId"] for r in rows} == WEEK_8
    assert len(rows) == len(WEEK_8)
    assert summary["season"] == 2026 and summary["week"] == 8
    assert set(summary["predicted"]) == WEEK_8
    for row in rows:
        assert set(row) == PREDICTION_FIELDS
        assert row["status"] == "OK"
        assert (row["season"], row["week"], row["stage"]) == (2026, 8, "REG")
        assert row["model_used"] == "nfl-elo-v1"
        assert row["generation"] == 1
        assert row["backfilled"] is False
        assert row["predicted_winner"] in row["matchId"]
        assert Decimal(0) <= row["home_win_probability"] <= Decimal(1)
        assert 0 <= row["margin_low"] <= row["margin_high"]


def test_predictions_use_ratings_from_strictly_before_the_target_week(tables, freeze):
    freeze(BEFORE_WEEK_8)
    run()
    games, _ = parse_csv(FIXTURE_CSV.read_text())
    ratings = replay_ratings(games, NFL, before=(2026, 8))
    by_id = {g.match_id: g for g in games}
    for row in scan(tables.predictions):
        expected = predict_game(
            by_id[row["matchId"]], ratings, random.Random(handler.rng_seed(row["matchId"]))
        )
        assert row["predicted_winner"] == expected.predicted_winner
        assert row["predicted_margin"] == expected.predicted_margin
        assert (row["margin_low"], row["margin_high"]) == (expected.margin_low, expected.margin_high)
        assert row["confidence"] == expected.confidence
        assert row["key_factors"] == expected.key_factors


def test_kickoff_is_stored_as_utc_z(tables, freeze):
    freeze(BEFORE_WEEK_8)
    run()
    row = next(r for r in scan(tables.predictions)
               if r["matchId"] == "nfl-2026-week-8-packers-v-panthers")
    # Thu 2026-10-29 20:15 EDT
    assert row["kickoff_utc"] == "2026-10-30T00:15:00Z"
    assert row["neutral"] is False


def test_only_current_season_games_are_upserted(tables, freeze):
    freeze(BEFORE_WEEK_8)
    run()
    items = scan(tables.games)
    games, _ = parse_csv(FIXTURE_CSV.read_text())
    assert {i["matchId"] for i in items} == {g.match_id for g in games if g.season == 2026}
    kc = next(i for i in items if i["matchId"] == "nfl-2026-week-8-broncos-v-chiefs")
    assert (kc["home_team"], kc["away_team"], kc["week"], kc["stage"]) == ("broncos", "chiefs", 8, "REG")
    assert kc["played"] is False and "home_score" not in kc
    tie = next(i for i in items if i["matchId"] == "nfl-2026-week-5-commanders-v-giants")
    assert (tie["home_score"], tie["away_score"], tie["played"]) == (27, 27, True)


def test_games_upsert_is_idempotent(tables, freeze):
    freeze(BEFORE_WEEK_8)
    run()
    first = len(scan(tables.games))
    run()
    assert len(scan(tables.games)) == first


# --- 3.2 ---------------------------------------------------------------------------

def test_unscored_earlier_game_within_72h_blocks_and_alarms(tables, freeze, csv_with, caplog):
    csv_with(unscore("2026_07_CIN_BAL"))  # kicked off 2026-10-25 17:00Z
    freeze("2026-10-27T12:00:00+00:00")  # 43h later
    with caplog.at_level(logging.WARNING):
        summary = run()
    assert scan(tables.predictions) == []
    assert "nfl-2026-week-7-ravens-v-bengals" in caplog.text
    assert summary["blocked_by"] == ["nfl-2026-week-7-ravens-v-bengals"]
    assert summary["unpredicted"] == 4
    assert unpredicted_metric_values() == [4.0]


def test_unscored_earlier_game_past_72h_is_cancelled_and_week_8_predicted(
    tables, freeze, csv_with, caplog
):
    csv_with(unscore("2026_07_CIN_BAL"))
    freeze("2026-10-28T18:00:00+00:00")  # 73h after kickoff
    with caplog.at_level(logging.WARNING):
        summary = run()
    assert {r["matchId"] for r in scan(tables.predictions)} == WEEK_8
    assert "treated as cancelled" in caplog.text
    assert "nfl-2026-week-7-ravens-v-bengals" in caplog.text
    assert summary["cancelled"] == ["nfl-2026-week-7-ravens-v-bengals"]
    assert unpredicted_metric_values() == [0.0]


# --- 3.3 ---------------------------------------------------------------------------

def test_kicked_off_game_is_not_predicted(tables, freeze):
    freeze("2026-10-30T01:00:00+00:00")  # after Thursday CAR@GB, before Sunday
    run()
    assert {r["matchId"] for r in scan(tables.predictions)} == WEEK_8 - {
        "nfl-2026-week-8-packers-v-panthers"
    }


def test_game_kicking_off_exactly_now_is_not_predicted(tables, freeze):
    freeze("2026-10-30T00:15:00+00:00")
    run()
    assert "nfl-2026-week-8-packers-v-panthers" not in {
        r["matchId"] for r in scan(tables.predictions)
    }


# --- 3.4 ---------------------------------------------------------------------------

def test_second_run_writes_no_new_rows(tables, freeze):
    freeze(BEFORE_WEEK_8)
    run()
    first = scan(tables.predictions)
    summary = run()
    assert len(scan(tables.predictions)) == len(first)
    assert summary["predicted"] == []
    assert set(summary["skipped"]) == WEEK_8


def test_a_failed_row_does_not_count_as_predicted(tables, freeze):
    freeze(BEFORE_WEEK_8)
    tables.predictions.put_item(Item={
        "matchId": "nfl-2026-week-8-jets-v-raiders",
        "generatedAt": "2026-10-27T12:00:00+00:00",
        "status": "FAILED",
        "error": "boom",
        "scraped_at": "2026-10-27T12:00:00+00:00",
    })
    run()
    rows = sorted(
        (r for r in scan(tables.predictions) if r["matchId"] == "nfl-2026-week-8-jets-v-raiders"),
        key=lambda r: r["generatedAt"],
    )
    assert [r["status"] for r in rows] == ["FAILED", "OK"]
    assert rows[-1]["generation"] == 2


# --- 3.5 ---------------------------------------------------------------------------

def test_every_item_written_has_scraped_at(tables, freeze):
    freeze(BEFORE_WEEK_8)
    run()
    assert all("scraped_at" in i for i in scan(tables.games))
    assert all("scraped_at" in i for i in scan(tables.predictions))
    assert scan(tables.games) and scan(tables.predictions)


@pytest.mark.parametrize("missing", ["NFL_GAMES_TABLE", "NFL_PREDICTIONS_TABLE"])
def test_missing_table_env_var_raises_before_any_network_call(
    tables, freeze, monkeypatch, missing
):
    freeze(BEFORE_WEEK_8)
    monkeypatch.delenv(missing)
    calls = []
    monkeypatch.setattr(handler, "fetch_csv", lambda url: calls.append(url) or "")
    with pytest.raises(KeyError, match=missing):
        run()
    assert calls == []


def test_csv_url_comes_from_env(tables, freeze, monkeypatch):
    freeze(BEFORE_WEEK_8)
    seen = []
    real = handler.fetch_csv
    monkeypatch.setattr(handler, "fetch_csv", lambda url: seen.append(url) or real(url))
    run()
    assert seen == [FIXTURE_CSV.as_uri()]


def test_csv_url_defaults_to_nflverse(monkeypatch):
    monkeypatch.delenv("NFL_GAMES_CSV_URL", raising=False)
    assert handler.csv_url() == (
        "https://github.com/nflverse/nfldata/raw/master/data/games.csv"
    )


# --- 3.6 ---------------------------------------------------------------------------

def test_prediction_rows_carry_no_market_data(tables, freeze):
    freeze(BEFORE_WEEK_8)
    run()
    for row in scan(tables.predictions):
        assert not [k for k in row if MARKET_PATTERN.search(k)]


def test_game_rows_keep_market_data_under_a_separate_map(tables, freeze):
    freeze(BEFORE_WEEK_8)
    run()
    items = {i["matchId"]: i for i in scan(tables.games)}
    for item in items.values():
        assert not [k for k in item if k != "market" and MARKET_PATTERN.search(k)]
    _, markets = parse_csv(FIXTURE_CSV.read_text())
    with_market = [mid for mid in items if mid in markets]
    assert with_market, "fixture should have 2026 rows with market data"
    for mid in with_market:
        market = items[mid]["market"]
        assert set(market) <= {"spread_line", "home_moneyline", "away_moneyline"}
        if markets[mid].spread_line is not None:
            assert market["spread_line"] == Decimal(str(markets[mid].spread_line))
    assert all("market" not in items[mid] for mid in items if mid not in markets)


# --- 3.7 ---------------------------------------------------------------------------

@pytest.mark.parametrize("error", [
    urllib.error.HTTPError("https://x", 500, "Server Error", None, None),  # type: ignore[arg-type]
    TimeoutError("timed out"),
])
def test_fetch_failure_raises_and_writes_nothing(tables, freeze, monkeypatch, error):
    freeze(BEFORE_WEEK_8)

    def boom(*args, **kwargs):
        raise error

    monkeypatch.setattr(handler.urllib.request, "urlopen", boom)
    with pytest.raises(type(error)):
        run()
    assert scan(tables.games) == [] and scan(tables.predictions) == []


def test_missing_file_url_raises(tables, freeze, monkeypatch, tmp_path):
    freeze(BEFORE_WEEK_8)
    monkeypatch.setenv("NFL_GAMES_CSV_URL", (tmp_path / "nope.csv").as_uri())
    with pytest.raises(urllib.error.URLError):
        run()
    assert scan(tables.games) == []


def test_malformed_csv_raises_and_writes_nothing(tables, freeze, csv_with):
    path = csv_with(lambda rows: rows)
    text = path.read_text().replace("location", "venue_kind", 1)
    path.write_text(text)
    freeze(BEFORE_WEEK_8)
    with pytest.raises(ValueError, match="location"):
        run()
    assert scan(tables.games) == [] and scan(tables.predictions) == []


# --- 3.8 ---------------------------------------------------------------------------

def test_one_failing_game_writes_failed_row_and_the_rest_ok(tables, freeze, monkeypatch, caplog):
    freeze(BEFORE_WEEK_8)
    real = handler.predict_game

    def flaky(game, *args, **kwargs):
        if game.match_id == "nfl-2026-week-8-broncos-v-chiefs":
            raise RuntimeError("forced failure")
        return real(game, *args, **kwargs)

    monkeypatch.setattr(handler, "predict_game", flaky)
    summary = run()
    rows = {r["matchId"]: r for r in scan(tables.predictions)}
    failed = rows["nfl-2026-week-8-broncos-v-chiefs"]
    assert failed["status"] == "FAILED"
    assert "forced failure" in failed["error"]
    assert "scraped_at" in failed and failed["model_used"] == "nfl-elo-v1"
    assert {m for m, r in rows.items() if r["status"] == "OK"} == WEEK_8 - {
        "nfl-2026-week-8-broncos-v-chiefs"
    }
    assert summary["failed"] == ["nfl-2026-week-8-broncos-v-chiefs"]
    assert summary["unpredicted"] == 1
    assert unpredicted_metric_values() == [1.0]


# --- edge cases --------------------------------------------------------------------

def test_no_future_games_predicts_nothing_without_alarming(tables, freeze, csv_with):
    """Week 18 done, Wild Card rows not yet published: quiet no-op, metric 0."""
    csv_with(lambda rows: [r for r in rows if not (r["season"] == "2026" and int(r["week"]) >= 8)])
    freeze(BEFORE_WEEK_8)
    summary = run()
    assert scan(tables.predictions) == []
    assert summary["week"] is None
    assert unpredicted_metric_values() == [0.0]


def test_fully_predicted_run_emits_zero(tables, freeze):
    freeze(BEFORE_WEEK_8)
    run()
    assert unpredicted_metric_values() == [0.0]


def test_metric_failure_does_not_abort_the_run(tables, freeze, monkeypatch):
    freeze(BEFORE_WEEK_8)
    real_client = handler.boto3.client

    def client(service, *args, **kwargs):
        if service == "cloudwatch":
            raise RuntimeError("cloudwatch down")
        return real_client(service, *args, **kwargs)

    monkeypatch.setattr(handler.boto3, "client", client)
    summary = run()
    assert set(summary["predicted"]) == WEEK_8


def test_real_clock_is_utc_aware():
    now = handler._now()
    assert now.tzinfo is not None and now.utcoffset() == timedelta(0)


def test_csv_url_scheme_is_allow_listed():
    """Characterisation (refactor step): only https:// and file:// are fetched."""
    with pytest.raises(ValueError, match="https:// or file://"):
        handler.fetch_csv("ftp://example.com/games.csv")
