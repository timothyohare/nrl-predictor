"""Walk-forward NFL backtest: fit the Elo constants on early seasons, then predict
every later game from ratings as they stood before its week, and grade the
predictions against the result, a home-team baseline and the betting market.

Metric definitions are fixed by the spec (.claude/sdlc/nfl-predictor/spec.md,
Phase 2) so numbers stay comparable:

- accuracy excludes ties;
- Brier is probabilistic, ``(p_home - outcome)^2`` with a tie scored 0.5, and
  includes ties;
- margin MAE is ``|signed predicted home margin - result|``;
- home baseline: always pick home, ``p_home`` = training-window home win rate
  (decided games), margin = mean training ``result``;
- market baseline (comparison only, never model input): pick the spread
  favourite (``spread_line`` 0 or blank skipped), ``p_home`` = de-vigged
  moneyline probability, margin = ``spread_line``;
- every week-N game is predicted from ratings after all games before week N.

The fit and the predictions only ever see `Game`, which has no market fields;
`Market` is read solely by `market_scored`.
"""
from __future__ import annotations

import hashlib
import itertools
import random
import statistics
from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass, replace

from common.nfl.games import Game, Market, parse_csv
from common.nfl.model import NFL, predict_game
from common.stats_model.elo import expected_score, update_ratings
from common.stats_model.ratings import regress_ratings
from common.stats_model.sport import SportModel

FIT_GRID_K = (10.0, 15.0, 20.0, 25.0, 30.0, 35.0)
FIT_GRID_HOME_ADVANTAGE = tuple(float(h) for h in range(20, 85, 5))
FIT_GRID_REGRESSION = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7)
# The first training season only warms ratings up from the starting value; it is
# excluded from the fit objective and the margin/confidence fits.
BURN_IN_SEASONS = 1

# Spec criterion 2.12 (confirmed by the user, 2026-10-28). Never lower these.
BAR_MIN_ACCURACY = 0.620
BAR_MIN_EDGE_OVER_HOME = 0.05
BAR_MAX_BRIER = 0.230

CONFIDENCE_LEVELS = ("HIGH", "MEDIUM", "LOW")


# ---------------------------------------------------------------------------
# Walk-forward ratings
# ---------------------------------------------------------------------------

def pregame_ratings(
    games: Iterable[Game], model: SportModel, from_season: int | None = None
) -> Iterator[tuple[Game, float, float]]:
    """Yield ``(game, home_rating, away_rating)`` for every game (played or not)
    with ratings as they stood before the game's week — exactly what
    ``replay_ratings(games, model, before=(season, week))`` returns, computed
    incrementally. Same ordering and season-regression rules as replay_ratings.
    """
    ratings: defaultdict[str, float] = defaultdict(lambda: model.starting_rating)
    current_season: int | None = None
    ordered = sorted(games, key=lambda g: (g.season, g.week, g.home, g.away))
    for (season, _week), group in itertools.groupby(ordered, key=lambda g: (g.season, g.week)):
        week_games = list(group)
        if current_season is not None and season > current_season:
            if model.season_regression:
                regress_ratings(ratings, model, seasons=season - current_season)
            current_season = season
        if from_season is None or season >= from_season:
            for game in week_games:
                yield game, ratings[game.home], ratings[game.away]
        for game in week_games:
            if game.home_score is None or game.away_score is None:
                continue
            current_season = season
            ratings[game.home], ratings[game.away] = update_ratings(
                ratings[game.home], ratings[game.away], game.home_score, game.away_score,
                home_advantage=_home_advantage(game, model), model=model,
            )


def _home_advantage(game: Game, model: SportModel) -> float:
    return 0.0 if game.neutral else model.home_advantage


def _outcome(result: int) -> float:
    return 1.0 if result > 0 else 0.0 if result < 0 else 0.5


# ---------------------------------------------------------------------------
# Fit (training seasons only)
# ---------------------------------------------------------------------------

def _scored_training(
    games: Sequence[Game], model: SportModel, first_scored: int
) -> Iterator[tuple[float, int]]:
    """(home_effective - away, result) for every played training game past the burn-in."""
    for game, home_rating, away_rating in pregame_ratings(games, model, from_season=first_scored):
        if game.result is not None:
            yield home_rating + _home_advantage(game, model) - away_rating, game.result


def _brier_for(games: Sequence[Game], model: SportModel, first_scored: int) -> float:
    errors = [
        (expected_score(diff, 0.0) - _outcome(result)) ** 2
        for diff, result in _scored_training(games, model, first_scored)
    ]
    return sum(errors) / len(errors)


def fit(games: Iterable[Game], eval_from: int) -> SportModel:
    """Fit the NFL constants on seasons strictly before `eval_from` only.

    K, home advantage and season regression: grid search minimising Brier of the
    closed-form Elo probability. Then, at those values: the margin model
    ``|result| ~ |elo_diff|`` by least squares (residual stdev), and confidence
    thresholds at the terciles of ``|p_home - 0.5|``. Returned at the precision
    committed in common/nfl/model.py.
    """
    training = [g for g in games if g.season < eval_from]
    seasons = sorted({g.season for g in training if g.played})
    if not seasons:
        raise ValueError(f"no played games before {eval_from} to fit on")
    first_scored = seasons[min(BURN_IN_SEASONS, len(seasons) - 1)]

    best: tuple[float, SportModel] | None = None
    for k, hfa, regression in itertools.product(
        FIT_GRID_K, FIT_GRID_HOME_ADVANTAGE, FIT_GRID_REGRESSION
    ):
        candidate = replace(NFL, k_factor=k, home_advantage=hfa, season_regression=regression)
        brier = _brier_for(training, candidate, first_scored)
        if best is None or brier < best[0]:
            best = (brier, candidate)
    assert best is not None
    model = best[1]

    pairs = [
        (abs(diff), abs(result)) for diff, result in _scored_training(training, model, first_scored)
    ]
    xs, ys = [x for x, _ in pairs], [y for _, y in pairs]
    slope, intercept = statistics.linear_regression(xs, ys)
    residuals = [y - (slope * x + intercept) for x, y in pairs]
    distances = [abs(expected_score(x, 0.0) - 0.5) for x in xs]
    medium, high = statistics.quantiles(distances, n=3)
    return replace(
        model,
        margin_slope=round(slope, 4),
        margin_intercept=round(intercept, 2),
        margin_stdev=round(statistics.pstdev(residuals), 2),
        medium_threshold=round(medium, 3),
        high_threshold=round(high, 3),
    )


# ---------------------------------------------------------------------------
# Predictions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GamePrediction:
    match_id: str
    season: int
    week: int
    home: str
    away: str
    neutral: bool
    p_home: float
    pick_home: bool
    margin: int  # signed, home perspective
    confidence: str
    result: int  # home - away


def predict_walk_forward(
    games: Iterable[Game],
    model: SportModel,
    eval_from: int,
    eval_to: int,
    *,
    n_simulations: int,
    seed: int = 0,
) -> list[GamePrediction]:
    """Predict every played game in ``[eval_from, eval_to]`` from pre-week ratings.

    Each game gets its own rng seeded from ``seed`` and its matchId, so a
    prediction never depends on how many games were simulated before it.
    """
    out: list[GamePrediction] = []
    for game, home_rating, away_rating in pregame_ratings(games, model, from_season=eval_from):
        if game.season > eval_to or game.result is None:
            continue
        pred = predict_game(
            game, {game.home: home_rating, game.away: away_rating},
            random.Random(f"{seed}:{game.match_id}"), model=model, n_simulations=n_simulations,
        )
        pick_home = pred.predicted_winner == game.home
        out.append(GamePrediction(
            match_id=game.match_id, season=game.season, week=game.week,
            home=game.home, away=game.away, neutral=game.neutral,
            p_home=pred.home_win_probability, pick_home=pick_home,
            margin=pred.predicted_margin if pick_home else -pred.predicted_margin,
            confidence=pred.confidence, result=game.result,
        ))
    return out


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Scored:
    """One game as graded by a predictor. ``None`` = this predictor offers no
    pick/probability/margin for the game, so it is left out of that metric."""

    result: int
    p_home: float | None
    pick_home: bool | None
    margin: float | None


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def summarise(rows: Sequence[Scored]) -> dict:
    hits = [
        float(r.pick_home == (r.result > 0))
        for r in rows if r.pick_home is not None and r.result != 0
    ]
    briers = [(r.p_home - _outcome(r.result)) ** 2 for r in rows if r.p_home is not None]
    errors = [abs(r.margin - r.result) for r in rows if r.margin is not None]
    return {
        "n": len(rows),
        "accuracy": _mean(hits),
        "brier": _mean(briers),
        "margin_mae": _mean(errors),
        "n_accuracy": len(hits),
        "n_brier": len(briers),
        "n_margin": len(errors),
    }


def model_scored(predictions: Iterable[GamePrediction]) -> list[Scored]:
    return [Scored(p.result, p.p_home, p.pick_home, p.margin) for p in predictions]


def home_baseline(training: Iterable[Game]) -> tuple[float, float]:
    """(p_home, margin): training home win rate over decided games, mean result."""
    results = [g.result for g in training if g.result is not None]
    decided = [r for r in results if r != 0]
    return sum(r > 0 for r in decided) / len(decided), sum(results) / len(results)


def home_scored(results: Iterable[int], p_home: float, margin: float) -> list[Scored]:
    return [Scored(r, p_home, True, margin) for r in results]


def _implied(moneyline: int) -> float:
    return 100 / (moneyline + 100) if moneyline > 0 else -moneyline / (-moneyline + 100)


def devig_home_probability(home_moneyline: int, away_moneyline: int) -> float | None:
    """De-vigged home win probability, or None when either line is not a valid
    American moneyline (those lie outside (-100, 100); 0/0 would divide by zero)."""
    if -100 < home_moneyline < 100 or -100 < away_moneyline < 100:
        return None
    home, away = _implied(home_moneyline), _implied(away_moneyline)
    return home / (home + away)


def market_scored(games: Iterable, markets: Mapping[str, Market]) -> list[Scored]:
    """Grade the betting market on each game (``games`` need ``match_id`` and ``result``)."""
    rows = []
    for game in games:
        market = markets.get(game.match_id)
        spread = market.spread_line if market else None
        p_home = None
        if market and market.home_moneyline is not None and market.away_moneyline is not None:
            p_home = devig_home_probability(market.home_moneyline, market.away_moneyline)
        rows.append(Scored(
            result=game.result,
            p_home=p_home,
            pick_home=None if not spread else spread > 0,
            margin=spread,
        ))
    return rows


def by_confidence(predictions: Iterable[GamePrediction]) -> dict:
    grouped: dict[str, list[GamePrediction]] = {level: [] for level in CONFIDENCE_LEVELS}
    for p in predictions:
        grouped[p.confidence].append(p)
    out = {}
    for level, preds in grouped.items():
        summary = summarise(model_scored(preds))
        out[level] = {"n": summary["n"], "accuracy": summary["accuracy"]}
    return out


def calibration_bins(predictions: Iterable[GamePrediction], n_bins: int = 10) -> list[dict]:
    """Ten equal-width bins of predicted p_home; observed home win rate counts a tie as 0.5."""
    bins: list[list[GamePrediction]] = [[] for _ in range(n_bins)]
    for p in predictions:
        bins[min(int(p.p_home * n_bins), n_bins - 1)].append(p)
    return [
        {
            "lo": round(i / n_bins, 10),
            "hi": round((i + 1) / n_bins, 10),
            "n": len(preds),
            "mean_p": _mean([p.p_home for p in preds]),
            "home_win_rate": _mean([_outcome(p.result) for p in preds]),
        }
        for i, preds in enumerate(bins)
    ]


# ---------------------------------------------------------------------------
# The whole run
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BacktestResult:
    report: dict
    predictions: list[GamePrediction]


def _overall_and_per_season(seasons: Sequence[int], rows: Sequence[Scored]) -> dict:
    per_season: dict[str, list[Scored]] = defaultdict(list)
    for season, row in zip(seasons, rows, strict=True):
        per_season[str(season)].append(row)
    return {
        "overall": summarise(rows),
        "per_season": {s: summarise(r) for s, r in sorted(per_season.items())},
    }


def run_backtest(
    data: bytes, eval_from: int, eval_to: int, *, n_simulations: int, seed: int = 0
) -> BacktestResult:
    games, markets = parse_csv(data.decode("utf-8"))
    model = fit(games, eval_from)
    predictions = predict_walk_forward(
        games, model, eval_from, eval_to, n_simulations=n_simulations, seed=seed
    )
    seasons = [p.season for p in predictions]
    model_block = _overall_and_per_season(seasons, model_scored(predictions))

    p_home, margin = home_baseline(g for g in games if g.season < eval_from)
    home_block = _overall_and_per_season(
        seasons, home_scored([p.result for p in predictions], p_home, margin)
    )
    market_block = _overall_and_per_season(seasons, market_scored(predictions, markets))

    report = {
        "data_sha256": hashlib.sha256(data).hexdigest(),
        "fit_window": [min(g.season for g in games), eval_from - 1],
        "eval_window": [eval_from, eval_to],
        "params": asdict(model),
        "n_simulations": n_simulations,
        "seed": seed,
        "overall": model_block["overall"],
        "per_season": model_block["per_season"],
        "baselines": {
            "home": {"p_home": p_home, "margin": margin, **home_block},
            "market": market_block,
        },
        "by_confidence": by_confidence(predictions),
        "calibration_bins": calibration_bins(predictions),
    }
    return BacktestResult(report=report, predictions=predictions)


def check_bar(report: Mapping) -> list[str]:
    """Spec criterion 2.12. Returns one message per missed condition ([] = bar met)."""
    model, home = report["overall"], report["baselines"]["home"]["overall"]
    failures = []
    if model["accuracy"] < BAR_MIN_ACCURACY:
        failures.append(f"accuracy {model['accuracy']:.4f} < {BAR_MIN_ACCURACY}")
    elif model["accuracy"] < home["accuracy"] + BAR_MIN_EDGE_OVER_HOME:
        failures.append(
            f"accuracy {model['accuracy']:.4f} < home baseline {home['accuracy']:.4f} "
            f"+ {BAR_MIN_EDGE_OVER_HOME}"
        )
    if model["brier"] > BAR_MAX_BRIER or model["brier"] >= home["brier"]:
        failures.append(
            f"Brier {model['brier']:.4f} must be <= {BAR_MAX_BRIER} and < home baseline "
            f"{home['brier']:.4f}"
        )
    if model["margin_mae"] >= home["margin_mae"]:
        failures.append(
            f"margin MAE {model['margin_mae']:.3f} >= home baseline {home['margin_mae']:.3f}"
        )
    acc = [report["by_confidence"][level]["accuracy"] for level in CONFIDENCE_LEVELS]
    if None in acc or not acc[0] > acc[1] > acc[2]:
        failures.append(f"by_confidence accuracy not strictly monotonic HIGH > MEDIUM > LOW: {acc}")
    return failures
