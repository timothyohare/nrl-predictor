"""Walk-forward NFL backtest engine and metrics (common/nfl/backtest.py) —
spec criteria 2.6, 2.7, 2.10 and the bar logic behind 2.12."""
from __future__ import annotations

import csv
import dataclasses
import hashlib
import io
import random

import pytest

from common.nfl import backtest
from common.nfl.backtest import (
    GamePrediction,
    Scored,
    by_confidence,
    calibration_bins,
    check_bar,
    devig_home_probability,
    fit,
    home_baseline,
    market_scored,
    predict_walk_forward,
    pregame_ratings,
    run_backtest,
    summarise,
)
from common.nfl.games import Market, parse_csv
from common.nfl.model import predict_game
from common.stats_model.ratings import replay_ratings

EVAL_FROM, EVAL_TO = 2020, 2025
SIMS = 300
MARKET_COLUMNS = (
    "away_moneyline", "home_moneyline", "spread_line", "away_spread_odds",
    "home_spread_odds", "total_line", "under_odds", "over_odds",
)


@pytest.fixture
def games(sample_csv_text):
    return parse_csv(sample_csv_text)[0]


@pytest.fixture
def model(games):
    return fit(games, EVAL_FROM)


def _rewrite(csv_text: str, edit) -> str:
    reader = csv.DictReader(io.StringIO(csv_text))
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=reader.fieldnames or [], lineterminator="\n")
    writer.writeheader()
    for row in reader:
        writer.writerow(edit(row))
    return out.getvalue()


# ---------------------------------------------------------------------------
# Walk-forward ratings: week semantics + parity with replay_ratings
# ---------------------------------------------------------------------------

def test_pregame_ratings_match_replay_ratings_before_each_week(games, model):
    seen = 0
    for game, home_rating, away_rating in pregame_ratings(games, model):
        replayed = replay_ratings(games, model, before=(game.season, game.week))
        assert (home_rating, away_rating) == (replayed[game.home], replayed[game.away])
        seen += 1
    assert seen == len(games)


def test_pregame_ratings_from_season_only_yields_later_games(games, model):
    yielded = [g for g, _, _ in pregame_ratings(games, model, from_season=EVAL_FROM)]
    assert yielded and all(g.season >= EVAL_FROM for g in yielded)


def test_every_game_in_a_week_uses_the_same_pre_week_ratings(games, model):
    """Week semantics: a week-N game never sees another week-N result."""
    for game, home_rating, _ in pregame_ratings(games, model):
        if game.match_id == "nfl-2003-week-2-chiefs-v-steelers":
            # KC also played (and won) in week 1; that result is in, nothing else from week 2 is.
            assert home_rating == replay_ratings(games, model, before=(2003, 2))["chiefs"]
            assert home_rating > model.starting_rating


# ---------------------------------------------------------------------------
# 2.7 — no look-ahead
# ---------------------------------------------------------------------------

def test_changing_a_week_n_score_never_changes_predictions_up_to_week_n(games, model):
    base = predict_walk_forward(games, model, EVAL_FROM, EVAL_TO, n_simulations=SIMS, seed=0)
    assert base
    for target in [g for g in games if g.played and g.season >= EVAL_FROM]:
        changed = [
            dataclasses.replace(g, home_score=0, away_score=63) if g is target else g for g in games
        ]
        after = predict_walk_forward(changed, model, EVAL_FROM, EVAL_TO, n_simulations=SIMS, seed=0)
        cutoff = (target.season, target.week)
        # Compare what was *predicted* — `result` is the graded outcome, which for
        # the edited game itself legitimately changes.
        assert [_predicted(p) for p in after if (p.season, p.week) <= cutoff] == [
            _predicted(p) for p in base if (p.season, p.week) <= cutoff
        ]
        if target.season <= EVAL_TO:  # sanity: the edit really reached the predicted set
            assert any(p.result != q.result for p, q in zip(after, base, strict=True))


def _predicted(p: GamePrediction) -> tuple:
    return (p.match_id, p.p_home, p.pick_home, p.margin, p.confidence)


def test_fit_ignores_every_eval_season_score(games, model):
    for target in [g for g in games if g.played and g.season >= EVAL_FROM]:
        changed = [
            dataclasses.replace(g, home_score=70, away_score=0) if g is target else g for g in games
        ]
        assert fit(changed, EVAL_FROM) == model


def test_fit_does_use_training_scores(games, model):
    target = next(g for g in games if g.season == 2003)
    changed = [dataclasses.replace(g, home_score=70, away_score=0) if g is target else g for g in games]
    assert fit(changed, EVAL_FROM) != model


def test_fit_returns_an_nfl_shaped_model_at_committed_precision(model):
    assert model.margin_step == 1
    assert model.home_label == "Home-field"
    assert model.k_factor in backtest.FIT_GRID_K
    assert model.home_advantage in backtest.FIT_GRID_HOME_ADVANTAGE
    assert model.season_regression in backtest.FIT_GRID_REGRESSION
    assert model.margin_slope == round(model.margin_slope, 4)
    assert model.margin_intercept == round(model.margin_intercept, 2)
    assert model.margin_stdev == round(model.margin_stdev, 2)
    assert model.medium_threshold == round(model.medium_threshold, 3)
    assert model.medium_threshold <= model.high_threshold


def test_fit_without_training_games_fails_loudly(games):
    with pytest.raises(ValueError):
        fit(games, 1999)


# ---------------------------------------------------------------------------
# 2.6 — odds never reach the model (behavioural half)
# ---------------------------------------------------------------------------

def _without_market(report: dict) -> dict:
    stripped = {k: v for k, v in report.items() if k != "data_sha256"}
    stripped["baselines"] = {k: v for k, v in report["baselines"].items() if k != "market"}
    return stripped


def test_backtest_is_invariant_to_scrambled_market_columns(sample_csv_text):
    rng = random.Random(42)

    def scramble(row):
        for col in MARKET_COLUMNS:
            if col in ("spread_line", "total_line"):
                row[col] = str(round(rng.uniform(-14, 14), 1))
            else:  # moneylines and juice are American odds integers
                row[col] = str(rng.choice([-1, 1]) * rng.randint(100, 900))
        return row

    scrambled = _rewrite(sample_csv_text, scramble)
    assert scrambled != sample_csv_text
    a = run_backtest(sample_csv_text.encode(), EVAL_FROM, EVAL_TO, n_simulations=SIMS)
    b = run_backtest(scrambled.encode(), EVAL_FROM, EVAL_TO, n_simulations=SIMS)
    assert a.predictions == b.predictions
    assert _without_market(a.report) == _without_market(b.report)
    assert a.report["baselines"]["market"] != b.report["baselines"]["market"]


# ---------------------------------------------------------------------------
# Neutral sites in the walk-forward
# ---------------------------------------------------------------------------

def test_walk_forward_neutral_game_has_no_home_advantage(games, model):
    preds = predict_walk_forward(games, model, EVAL_FROM, EVAL_TO, n_simulations=SIMS, seed=0)
    sb = next(p for p in preds if p.match_id == "nfl-2020-week-21-buccaneers-v-chiefs")
    assert sb.neutral is True
    ratings = {g.match_id: (h, a) for g, h, a in pregame_ratings(games, model)}
    h, a = ratings[sb.match_id]
    game = next(g for g in games if g.match_id == sb.match_id)
    rng = random.Random(f"0:{sb.match_id}")
    expected = predict_game(game, {game.home: h, game.away: a}, rng, model=model, n_simulations=SIMS)
    assert sb.p_home == expected.home_win_probability


def test_walk_forward_only_predicts_played_games_in_the_window(games, model):
    preds = predict_walk_forward(games, model, EVAL_FROM, EVAL_TO, n_simulations=SIMS, seed=0)
    assert {p.season for p in preds} == {2020, 2021, 2025}
    played = [g for g in games if g.played and EVAL_FROM <= g.season <= EVAL_TO]
    assert len(preds) == len(played)
    for p in preds:
        assert p.pick_home == (p.p_home >= 0.5)
        # Signed margin points at the pick (a rounded-to-0 margin is allowed either way).
        assert p.margin * (1 if p.pick_home else -1) >= 0
        assert p.confidence in {"HIGH", "MEDIUM", "LOW"}


# ---------------------------------------------------------------------------
# 2.10 — metric definitions, each pinned by a hand-computed example
# ---------------------------------------------------------------------------

def test_summarise_model_metrics_hand_computed():
    rows = [
        Scored(result=7, p_home=0.7, pick_home=True, margin=3),     # right, brier .09, err 4
        Scored(result=-3, p_home=0.6, pick_home=True, margin=2),    # wrong, brier .36, err 5
        Scored(result=0, p_home=0.4, pick_home=False, margin=-1),   # tie: not in accuracy, brier .01, err 1
        Scored(result=-10, p_home=0.2, pick_home=False, margin=-6), # right, brier .04, err 4
    ]
    out = summarise(rows)
    assert out["n"] == 4
    assert out["accuracy"] == pytest.approx(2 / 3)
    assert out["brier"] == pytest.approx((0.09 + 0.36 + 0.01 + 0.04) / 4)
    assert out["margin_mae"] == pytest.approx(3.5)


def test_summarise_with_nothing_to_score_is_none():
    out = summarise([Scored(result=0, p_home=None, pick_home=None, margin=None)])
    assert out == {"n": 1, "accuracy": None, "brier": None, "margin_mae": None,
                   "n_accuracy": 0, "n_brier": 0, "n_margin": 0}


def test_home_baseline_hand_computed(sample_csv_text):
    games = [g for g in parse_csv(sample_csv_text)[0] if g.season == 2002]
    # 2002 results: -28, 7, 14, 16, -5, 21, -13, 0 (tie) -> 4 home wins of 7 decided.
    p_home, margin = home_baseline(games)
    assert p_home == pytest.approx(4 / 7)
    assert margin == pytest.approx((-28 + 7 + 14 + 16 - 5 + 21 - 13 + 0) / 8)


def test_devig_moneylines():
    # -150 -> 0.6 implied; +130 -> 100/230. Normalised to sum to 1.
    ih, ia = 150 / 250, 100 / 230
    assert devig_home_probability(-150, 130) == pytest.approx(ih / (ih + ia))
    assert devig_home_probability(110, -130) == pytest.approx((100 / 210) / (100 / 210 + 130 / 230))


def test_market_metrics_hand_computed():
    def g(result):
        return type("G", (), {"result": result, "match_id": f"m{result}"})()

    games = [g(7), g(-3), g(4), g(0)]
    markets = {
        "m7": Market("m7", spread_line=3.0, home_moneyline=-150, away_moneyline=130),
        "m-3": Market("m-3", spread_line=-2.5, home_moneyline=None, away_moneyline=None),
        "m4": Market("m4", spread_line=0.0, home_moneyline=-110, away_moneyline=-110),
        # m0: no market row at all
    }
    rows = market_scored(games, markets)
    assert [r.pick_home for r in rows] == [True, False, None, None]
    out = summarise(rows)
    # Spread favourite right on m7 and m-3; m4 (pick'em) and m0 (no line) excluded.
    assert (out["accuracy"], out["n_accuracy"]) == (1.0, 2)
    p7 = devig_home_probability(-150, 130)
    assert out["n_brier"] == 2
    assert out["brier"] == pytest.approx(((p7 - 1) ** 2 + (0.5 - 1) ** 2) / 2)
    assert out["n_margin"] == 3
    assert out["margin_mae"] == pytest.approx((abs(3 - 7) + abs(-2.5 + 3) + abs(0 - 4)) / 3)


def _pred(p_home, confidence, result):
    pick = p_home >= 0.5
    return GamePrediction(
        match_id="x", season=2020, week=1, home="a", away="b", neutral=False, p_home=p_home,
        pick_home=pick, margin=3 if pick else -3, confidence=confidence, result=result,
    )


def test_by_confidence_hand_computed():
    preds = [
        _pred(0.8, "HIGH", 10), _pred(0.75, "HIGH", -3),
        _pred(0.6, "MEDIUM", 3), _pred(0.4, "MEDIUM", 0),
        _pred(0.52, "LOW", -1),
    ]
    out = by_confidence(preds)
    assert out["HIGH"] == {"n": 2, "accuracy": 0.5}
    assert out["MEDIUM"] == {"n": 2, "accuracy": 1.0}
    assert out["LOW"] == {"n": 1, "accuracy": 0.0}


def test_calibration_bins_hand_computed():
    preds = [_pred(0.05, "HIGH", -7), _pred(0.62, "LOW", 3), _pred(0.68, "LOW", 0), _pred(1.0, "HIGH", 9)]
    bins = calibration_bins(preds)
    assert len(bins) == 10
    assert bins[0] == {"lo": 0.0, "hi": 0.1, "n": 1, "mean_p": 0.05, "home_win_rate": 0.0}
    assert bins[6]["n"] == 2
    assert bins[6]["mean_p"] == pytest.approx(0.65)
    assert bins[6]["home_win_rate"] == pytest.approx(0.75)  # a win and a tie
    assert bins[9]["n"] == 1  # p == 1.0 lands in the top bin
    assert bins[3] == {"lo": 0.3, "hi": 0.4, "n": 0, "mean_p": None, "home_win_rate": None}


# ---------------------------------------------------------------------------
# Report shape (2.11) and the success bar (2.12)
# ---------------------------------------------------------------------------

def test_run_backtest_report_shape(sample_csv_text):
    result = run_backtest(sample_csv_text.encode(), EVAL_FROM, EVAL_TO, n_simulations=SIMS)
    r = result.report
    assert set(r) >= {"data_sha256", "fit_window", "eval_window", "params", "overall", "per_season",
                      "baselines", "by_confidence", "calibration_bins"}
    assert set(r["baselines"]) == {"home", "market"}
    assert set(r["overall"]) >= {"n", "accuracy", "brier", "margin_mae"}
    assert r["fit_window"] == [1999, 2019]
    assert r["eval_window"] == [2020, 2025]
    assert set(r["per_season"]) == {"2020", "2021", "2025"}
    assert r["overall"]["n"] == len(result.predictions)
    assert r["data_sha256"] == hashlib.sha256(sample_csv_text.encode()).hexdigest()
    assert r["params"]["k_factor"] == fit(parse_csv(sample_csv_text)[0], EVAL_FROM).k_factor


def _report(acc=0.64, brier=0.22, mae=10.0, home=(0.56, 0.245, 10.5), conf=(0.55, 0.62, 0.75)):
    return {
        "overall": {"accuracy": acc, "brier": brier, "margin_mae": mae},
        "baselines": {"home": {"overall": {"accuracy": home[0], "brier": home[1], "margin_mae": home[2]}}},
        "by_confidence": {"LOW": {"accuracy": conf[0]}, "MEDIUM": {"accuracy": conf[1]},
                          "HIGH": {"accuracy": conf[2]}},
    }


def test_check_bar_passes_a_clearing_report():
    assert check_bar(_report()) == []


@pytest.mark.parametrize(
    ("kwargs", "fragment"),
    [
        ({"acc": 0.619}, "accuracy"),
        ({"acc": 0.63, "home": (0.585, 0.245, 10.5)}, "home baseline"),
        ({"brier": 0.2301}, "Brier"),
        ({"brier": 0.225, "home": (0.56, 0.225, 10.5)}, "Brier"),
        ({"mae": 10.5}, "MAE"),
        ({"conf": (0.6, 0.6, 0.7)}, "monotonic"),
        ({"conf": (0.6, 0.7, 0.65)}, "monotonic"),
        ({"conf": (None, 0.7, 0.8)}, "monotonic"),
    ],
)
def test_check_bar_reports_each_miss(kwargs, fragment):
    failures = check_bar(_report(**kwargs))
    assert len(failures) == 1
    assert fragment in failures[0]


def test_check_bar_edge_values_are_inclusive_where_the_spec_says():
    # accuracy >= 0.620 and >= home + 0.05; Brier <= 0.230.
    assert check_bar(_report(acc=0.62, brier=0.23, home=(0.57, 0.245, 10.5))) == []
