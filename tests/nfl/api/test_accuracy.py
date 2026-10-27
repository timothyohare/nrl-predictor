"""GET /nfl/accuracy?season=YYYY (spec Phase 4, criterion 4.6) — every number
below is hand-computed from the seeded set using the Phase 2 metric definitions:
accuracy excludes ties; Brier is (p_home - outcome)^2 with a tie as 0.5; margin
MAE is |signed predicted home margin - result|."""
from __future__ import annotations

import pytest

from nfl.api import accuracy as handler
from tests.nfl.api.conftest import body, event, game, prediction, put

GB = "nfl-2026-week-7-packers-v-panthers"   # 24-17, home win (+7)
DEN = "nfl-2026-week-7-broncos-v-chiefs"    # 10-20, away win (-10)
NYJ = "nfl-2026-week-7-jets-v-raiders"      # 20-20 tie
BUF = "nfl-2026-week-8-bills-v-dolphins"    # unplayed


@pytest.fixture
def seeded(tables):
    put(tables.games,
        game(GB, score=(24, 17), market={"spread_line": 3.0, "home_moneyline": -150,
                                         "away_moneyline": 130}),
        game(DEN, score=(10, 20), market={"spread_line": -3.5}),
        game(NYJ, score=(20, 20), market={"spread_line": 0.0, "home_moneyline": -110,
                                          "away_moneyline": -110}),
        game(BUF),
        game("nfl-2025-week-7-packers-v-panthers", score=(0, 30)))
    put(tables.predictions,
        # superseded generation: must not be graded
        prediction(GB, winner="panthers", margin=9, p_home="0.2", confidence="LOW",
                   generated_at="2026-10-01T00:00:00+00:00"),
        prediction(GB, winner="packers", margin=3, p_home="0.7", confidence="HIGH"),
        prediction(DEN, winner="broncos", margin=2, p_home="0.55", confidence="LOW",
                   backfilled=True),
        prediction(NYJ, winner="raiders", margin=1, p_home="0.45", confidence="MEDIUM"),
        prediction(NYJ, winner="", status="FAILED", generated_at="2026-10-29T00:00:00+00:00"),
        prediction(BUF, winner="bills"),
        prediction("nfl-2026-week-7-rams-v-chargers", winner="rams"),  # orphan, no game
        prediction("nfl-2025-week-7-packers-v-panthers", winner="packers", p_home="0.9",
                   confidence="HIGH"))
    return tables


def get(query: dict | None = None) -> dict:
    return handler.lambda_handler(event("/nfl/accuracy", query=query), None)


def test_model_metrics_match_hand_computed_values(seeded):
    response = get({"season": "2026"})
    assert response["statusCode"] == 200
    assert response["headers"]["Content-Type"] == "application/json"
    data = body(response)
    assert data["season"] == 2026
    assert data["n"] == 3
    assert data["accuracy"] == pytest.approx(0.5)  # GB hit, DEN miss, tie excluded
    assert data["brier"] == pytest.approx((0.09 + 0.3025 + 0.0025) / 3)
    assert data["margin_mae"] == pytest.approx((4 + 12 + 1) / 3)
    assert data["n_backfilled"] == 1


def test_by_confidence(seeded):
    data = body(get({"season": "2026"}))
    assert data["by_confidence"] == {
        "HIGH": {"n": 1, "accuracy": 1.0},
        "MEDIUM": {"n": 1, "accuracy": None},  # the tie
        "LOW": {"n": 1, "accuracy": 0.0},
    }


def test_home_baseline_uses_the_training_window_constants(seeded):
    p, m = handler.HOME_BASELINE_P_HOME, handler.HOME_BASELINE_MARGIN
    # nflverse 1999-2015 (the model's fit window): home win rate and mean result.
    assert p == pytest.approx(0.5727, abs=1e-4)
    assert m == pytest.approx(2.60, abs=1e-2)
    home = body(get({"season": "2026"}))["baselines"]["home"]
    assert home["n"] == 3
    assert home["accuracy"] == pytest.approx(0.5)
    assert home["brier"] == pytest.approx(((p - 1) ** 2 + p ** 2 + (p - 0.5) ** 2) / 3)
    assert home["margin_mae"] == pytest.approx((abs(m - 7) + abs(m + 10) + abs(m)) / 3)


def test_market_baseline_is_comparison_only(seeded):
    market = body(get({"season": "2026"}))["baselines"]["market"]
    gb_home = 0.6 / (0.6 + 100 / 230)
    assert market["n"] == 3
    assert market["accuracy"] == pytest.approx(1.0)  # pick'em NYJ excluded
    assert market["n_accuracy"] == 2
    assert market["brier"] == pytest.approx(((gb_home - 1) ** 2 + 0.0) / 2)  # DEN has no moneylines
    assert market["margin_mae"] == pytest.approx((4 + 6.5 + 0) / 3)


def test_defaults_to_the_latest_season(seeded):
    assert body(get())["season"] == 2026
    assert body(get({}))["season"] == 2026


def test_other_season(seeded):
    data = body(get({"season": "2025"}))
    assert (data["season"], data["n"]) == (2025, 1)
    assert data["accuracy"] == pytest.approx(0.0)
    assert data["brier"] == pytest.approx(0.81)


def test_season_with_no_scored_predictions(tables):
    put(tables.games, game(BUF))
    put(tables.predictions, prediction(BUF, winner="bills"))
    data = body(get({"season": "2026"}))
    assert data["n"] == 0
    assert data["accuracy"] is None and data["brier"] is None and data["margin_mae"] is None


@pytest.mark.parametrize("season", ["abc", "20x6", "1800", "-2026", ""])
def test_bad_season_is_400(tables, season):
    response = get({"season": season})
    assert response["statusCode"] == 400
    assert "error" in body(response)


def test_unknown_season_is_404(seeded):
    assert get({"season": "2019"})["statusCode"] == 404


def test_empty_tables_is_404(tables):
    assert get()["statusCode"] == 404


# --- review N1 / N2 ------------------------------------------------------------

def test_malformed_prediction_row_is_skipped_and_logged(seeded, caplog):
    broken = prediction(GB, winner="packers", margin=3, p_home="0.7", confidence="HIGH",
                        generated_at="2026-10-30T00:00:00+00:00")
    del broken["home_win_probability"]
    no_confidence = prediction(DEN, winner="broncos", margin=2, p_home="0.55",
                               generated_at="2026-10-30T00:00:00+00:00")
    del no_confidence["confidence"]
    put(seeded.predictions, broken, no_confidence)
    with caplog.at_level("WARNING"):
        response = get({"season": "2026"})
    assert response["statusCode"] == 200
    data = body(response)
    assert data["n"] == 1  # only the NYJ tie is still gradable
    assert sum(level["n"] for level in data["by_confidence"].values()) == 1
    assert GB in caplog.text and DEN in caplog.text


def test_degenerate_moneylines_are_left_out_of_the_market_brier(tables):
    put(tables.games, game(GB, score=(24, 17), market={"spread_line": 3.0, "home_moneyline": 0,
                                                       "away_moneyline": 0}))
    put(tables.predictions, prediction(GB, winner="packers", margin=3, p_home="0.7"))
    response = get({"season": "2026"})
    assert response["statusCode"] == 200
    market = body(response)["baselines"]["market"]
    assert market["n"] == 1
    assert market["brier"] is None
    assert market["accuracy"] == pytest.approx(1.0)
