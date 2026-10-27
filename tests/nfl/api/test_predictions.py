"""GET /nfl/predictions/{season}/{week} (spec Phase 4, criteria 4.1-4.5)."""
from __future__ import annotations

import pytest

from nfl.api import predictions as handler
from tests.nfl.api.conftest import body, event, game, prediction, put

GB = "nfl-2026-week-8-packers-v-panthers"
DEN = "nfl-2026-week-8-broncos-v-chiefs"
NYJ = "nfl-2026-week-8-jets-v-raiders"


def get(season: str = "2026", week: str = "8") -> dict:
    return handler.lambda_handler(
        event(f"/nfl/predictions/{season}/{week}",
              path_parameters={"season": season, "week": week}), None)


def by_id(response: dict) -> dict[str, dict]:
    return {p["matchId"]: p for p in body(response)}


# --- 4.1 -----------------------------------------------------------------------

def test_newest_ok_generation_wins_and_failed_never_surfaces(tables):
    put(tables.games, game(GB))
    put(tables.predictions,
        prediction(GB, winner="panthers", generated_at="2026-10-27T12:00:00+00:00"),
        prediction(GB, winner="packers", generated_at="2026-10-28T12:00:00+00:00", generation=2),
        prediction(GB, winner="", generated_at="2026-10-29T12:00:00+00:00", status="FAILED"))
    response = get()
    assert response["statusCode"] == 200
    (pred,) = body(response)
    assert pred["predicted_winner"] == "packers"
    assert pred["generation"] == 2
    assert "error" not in pred and pred.get("status") in (None, "OK")


def test_response_is_json_with_ints_not_floats(tables):
    put(tables.games, game(GB))
    put(tables.predictions, prediction(GB, winner="packers", margin=7))
    response = get()
    assert response["headers"]["Content-Type"] == "application/json"
    (pred,) = body(response)
    assert pred["season"] == 2026 and isinstance(pred["season"], int)
    assert pred["week"] == 8 and isinstance(pred["week"], int)
    assert pred["predicted_margin"] == 7 and isinstance(pred["predicted_margin"], int)
    assert pred["home_win_probability"] == pytest.approx(0.6)


def test_carries_teams_names_and_prediction_fields(tables):
    put(tables.games, game(GB, kickoff="2026-10-30T00:15:00Z"))
    put(tables.predictions, prediction(GB, winner="packers", backfilled=True))
    (pred,) = body(get())
    assert (pred["home_team"], pred["away_team"]) == ("packers", "panthers")
    assert (pred["home_team_name"], pred["away_team_name"]) == ("Packers", "Panthers")
    assert pred["predicted_winner_name"] == "Packers"
    assert pred["kickoff_utc"] == "2026-10-30T00:15:00Z"
    assert pred["backfilled"] is True
    assert (pred["stage"], pred["label"]) == ("REG", "Week 8")
    for key in ("margin_low", "margin_high", "confidence", "key_factors", "reasoning",
                "model_used", "generatedAt"):
        assert key in pred


def test_sorted_by_kickoff_then_match_id(tables):
    put(tables.games,
        game(DEN, kickoff="2026-11-01T21:25:00Z"),
        game(NYJ, kickoff="2026-11-01T18:00:00Z"),
        game("nfl-2026-week-8-bills-v-dolphins", kickoff="2026-11-01T18:00:00Z"),
        game(GB, kickoff="2026-10-30T00:15:00Z"))
    put(tables.predictions,
        prediction(DEN, winner="chiefs"), prediction(NYJ, winner="jets"),
        prediction("nfl-2026-week-8-bills-v-dolphins", winner="bills"),
        prediction(GB, winner="packers"))
    assert [p["matchId"] for p in body(get())] == [
        GB, "nfl-2026-week-8-bills-v-dolphins", NYJ, DEN,
    ]


def test_only_the_requested_season_and_week(tables):
    other = "nfl-2026-week-9-packers-v-panthers"
    put(tables.games, game(GB), game(other))
    put(tables.predictions, prediction(GB, winner="packers"), prediction(other, winner="packers"))
    assert list(by_id(get())) == [GB]


def test_prediction_for_a_game_no_longer_in_nfl_games_is_dropped(tables):
    """Review N9: a rescheduled game leaves an orphan row under its old matchId."""
    put(tables.games, game(GB))
    put(tables.predictions, prediction(GB, winner="packers"),
        prediction("nfl-2026-week-8-bills-v-dolphins", winner="bills"))
    assert list(by_id(get())) == [GB]


def test_week_with_only_orphans_is_404(tables):
    put(tables.predictions, prediction(GB, winner="packers"))
    assert get()["statusCode"] == 404


# --- 4.2 -----------------------------------------------------------------------

@pytest.mark.parametrize(("season", "week"), [
    ("abc", "8"), ("2026", "x"), ("2026", "8.5"), ("2026", "-1"), ("", "8"),
    ("2026", "0"), ("2026", "99"), ("1800", "8"), ("99999", "8"), ("２０２６", "8"),
])
def test_bad_season_or_week_is_400(tables, season, week):
    response = get(season, week)
    assert response["statusCode"] == 400
    assert "error" in body(response)
    assert response["headers"]["Content-Type"] == "application/json"


def test_missing_path_parameters_is_400(tables):
    response = handler.lambda_handler(event("/nfl/predictions"), None)
    assert response["statusCode"] == 400


def test_no_predictions_is_404(tables):
    put(tables.games, game(GB))
    response = get("2026", "17")
    assert response["statusCode"] == 404
    assert "error" in body(response)


def test_failed_only_is_404(tables):
    put(tables.games, game(GB))
    put(tables.predictions, prediction(GB, winner="", status="FAILED"))
    assert get()["statusCode"] == 404


# --- 4.3 -----------------------------------------------------------------------

def test_join_is_round_aware(tables):
    old = "nfl-2025-week-3-packers-v-panthers"
    put(tables.games, game(old, score=(10, 31)), game(GB, score=(27, 20)))
    put(tables.predictions, prediction(old, winner="panthers"), prediction(GB, winner="packers"))
    (pred_2026,) = body(get("2026", "8"))
    (pred_2025,) = body(get("2025", "3"))
    assert pred_2026["result"]["home_score"] == 27
    assert pred_2026["result"]["winner"] == "packers"
    assert pred_2025["result"]["home_score"] == 10
    assert pred_2025["result"]["winner"] == "panthers"


# --- 4.4 -----------------------------------------------------------------------

def test_played_game_carries_the_result(tables):
    put(tables.games, game(GB, score=(17, 24)))
    put(tables.predictions, prediction(GB, winner="packers"))
    (pred,) = body(get())
    assert pred["result"] == {
        "home_score": 17, "away_score": 24, "winner": "panthers",
        "winner_name": "Panthers", "margin": 7,
    }


def test_unplayed_game_has_no_result(tables):
    put(tables.games, game(GB))
    put(tables.predictions, prediction(GB, winner="packers"))
    (pred,) = body(get())
    assert "result" not in pred


def test_tie_has_a_null_winner(tables):
    put(tables.games, game(GB, score=(20, 20)))
    put(tables.predictions, prediction(GB, winner="packers"))
    (pred,) = body(get())
    assert pred["result"]["winner"] is None
    assert pred["result"]["winner_name"] is None
    assert pred["result"]["margin"] == 0


def test_neutral_comes_from_the_game(tables):
    mid = "nfl-2025-week-1-chargers-v-chiefs"
    put(tables.games, game(mid, neutral=True))
    put(tables.predictions, prediction(mid, winner="chiefs"))
    (pred,) = body(get("2025", "1"))
    assert pred["neutral"] is True


@pytest.mark.parametrize(("season", "week"), [("2020", "18"), ("2025", "19")])
def test_wild_card_label_whatever_the_week_number(tables, season, week):
    mid = f"nfl-{season}-week-{week}-bills-v-dolphins"
    put(tables.games, game(mid, stage="WC"))
    put(tables.predictions, prediction(mid, winner="bills"))
    (pred,) = body(get(season, week))
    assert (pred["stage"], pred["label"]) == ("WC", "Wild Card")


def test_regular_season_week_18_is_labelled_week_18(tables):
    mid = "nfl-2025-week-18-bills-v-dolphins"
    put(tables.games, game(mid))
    put(tables.predictions, prediction(mid, winner="bills"))
    (pred,) = body(get("2025", "18"))
    assert pred["label"] == "Week 18"


# --- market + 4.5 ------------------------------------------------------------------

def test_market_block(tables):
    # spread_line > 0: the home team (Packers) is favoured; -198/+164 moneylines.
    put(tables.games, game(GB, market={"spread_line": 3.5, "home_moneyline": -198,
                                       "away_moneyline": 164}))
    put(tables.predictions, prediction(GB, winner="packers"))
    (pred,) = body(get())
    market = pred["market"]
    assert market["spread_favourite"] == "packers"
    assert market["spread_line"] == 3.5
    home, away = 198 / 298, 100 / 264
    assert market["implied_home_prob"] == pytest.approx(home / (home + away))
    assert not [k for k in pred if "moneyline" in k]


def test_market_with_away_favourite_and_no_moneylines(tables):
    put(tables.games, game(DEN, market={"spread_line": -1.5}))
    put(tables.predictions, prediction(DEN, winner="chiefs"))
    (pred,) = body(get())
    assert pred["market"] == {"spread_favourite": "chiefs", "spread_line": -1.5,
                              "implied_home_prob": None}


@pytest.mark.parametrize(("winner", "margin", "spread", "expected"), [
    ("packers", 4, 3.5, False),   # agree, |4 - 3.5| = 0.5
    ("packers", 6, 3.0, False),   # agree, |diff| exactly 3
    ("packers", 7, 3.5, True),    # agree, |7 - 3.5| = 3.5 > 3
    ("packers", 1, 6.5, True),    # agree, |1 - 6.5| = 5.5 > 3
    ("panthers", 1, 1.5, True),   # different favourite, margins close
    ("panthers", 2, -1.5, False),  # away favourite agreed: signed -2 vs -1.5
    ("panthers", 8, -2.5, True),  # away favourite agreed: |-8 - -2.5| = 5.5
])
def test_is_outlier_truth_table(tables, winner, margin, spread, expected):
    put(tables.games, game(GB, market={"spread_line": spread}))
    put(tables.predictions, prediction(GB, winner=winner, margin=margin))
    (pred,) = body(get())
    assert pred["is_outlier"] is expected


def test_pick_em_spread_is_judged_on_margin_only(tables):
    """spread_line 0 has no favourite, so only the margin gap can flag it."""
    put(tables.games, game(GB, market={"spread_line": 0.0}), game(DEN, market={"spread_line": 0.0}))
    put(tables.predictions, prediction(GB, winner="panthers", margin=2),
        prediction(DEN, winner="broncos", margin=5))
    preds = by_id(get())
    assert preds[GB]["market"]["spread_favourite"] is None
    assert preds[GB]["is_outlier"] is False
    assert preds[DEN]["is_outlier"] is True


@pytest.mark.parametrize("market", [None, {"home_moneyline": -150, "away_moneyline": 130}])
def test_no_spread_means_no_outlier_field(tables, market):
    put(tables.games, game(GB, market=market))
    put(tables.predictions, prediction(GB, winner="packers"))
    (pred,) = body(get())
    assert "is_outlier" not in pred
    assert ("market" in pred) is (market is not None)


# --- review N1: one malformed row never takes the whole week down ---------------

def test_malformed_ok_row_is_skipped_and_logged(tables, caplog):
    put(tables.games, game(GB), game(DEN), game(NYJ, market={"spread_line": 3.0}))
    broken = prediction(DEN, winner="chiefs")
    del broken["predicted_winner"]
    unparsable = prediction(NYJ, winner="raiders")
    unparsable["predicted_margin"] = "seven"
    put(tables.predictions, prediction(GB, winner="packers"), broken, unparsable)
    with caplog.at_level("WARNING"):
        response = get()
    assert response["statusCode"] == 200
    assert [p["matchId"] for p in body(response)] == [GB]
    assert DEN in caplog.text and NYJ in caplog.text


def test_malformed_game_row_is_skipped(tables, caplog):
    put(tables.games, game(GB))
    bad_game = game(DEN)
    del bad_game["stage"]
    put(tables.games, bad_game)
    put(tables.predictions, prediction(GB, winner="packers"), prediction(DEN, winner="chiefs"))
    with caplog.at_level("WARNING"):
        response = get()
    assert response["statusCode"] == 200
    assert [p["matchId"] for p in body(response)] == [GB]
    assert DEN in caplog.text


def test_week_of_only_malformed_rows_is_404(tables):
    put(tables.games, game(GB))
    broken = prediction(GB, winner="packers")
    del broken["predicted_winner"]
    put(tables.predictions, broken)
    assert get()["statusCode"] == 404


# --- review N2: degenerate moneylines never 500 the week -----------------------

@pytest.mark.parametrize(("home_ml", "away_ml"), [(0, 0), (0, -110), (-110, 0), (50, -110)])
def test_degenerate_moneylines_have_no_implied_probability(tables, home_ml, away_ml):
    put(tables.games, game(GB, market={"spread_line": 3.5, "home_moneyline": home_ml,
                                       "away_moneyline": away_ml}))
    put(tables.predictions, prediction(GB, winner="packers"))
    response = get()
    assert response["statusCode"] == 200
    (pred,) = body(response)
    assert pred["market"] == {"spread_favourite": "packers", "spread_line": 3.5,
                              "implied_home_prob": None}
