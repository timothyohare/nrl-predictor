"""The NFL `SportModel` and its per-game prediction wrapper.

Elo + Monte Carlo only: no injury, QB, weather or rest signal, and never any
betting-market input (`Game` has no market fields — see common/nfl/games.py).
"""
from __future__ import annotations

import random
from collections.abc import Mapping

from common.nfl.games import Game
from common.stats_model.predictor import StatsPrediction, predict_match
from common.stats_model.sport import SportModel

N_SIMULATIONS = 10000

# Fitted 2026-10-28 on nflverse games.csv seasons 1999-2015 ONLY (1999 is the
# rating burn-in, so the objective covers 2000-2015); 2016+ is the walk-forward
# evaluation window and never touches these numbers. Data:
#   https://github.com/nflverse/nfldata/raw/master/data/games.csv
#   sha256 923f23dffe98534ad2305c7f38167e14e56f985b62e978b4e931f119e9405313
# Method (common/nfl/backtest.py::fit): grid search K x home advantage x season
# regression minimising Brier of the closed-form Elo probability; then
# |result| ~ |elo_diff| least squares for the margin model; confidence thresholds
# at the terciles of |p_home - 0.5|. Reproduce (criterion 2.13):
#   .venv/bin/python scripts/nfl_backtest.py --csv <games.csv> --eval-from 2016 --fit-only
# Precision: K/home advantage/regression are grid values; slope 4 dp,
# intercept/stdev 2 dp, thresholds 3 dp.
NFL = SportModel(
    k_factor=20.0,
    home_advantage=55.0,
    margin_slope=0.0163,
    margin_intercept=10.11,
    margin_stdev=9.28,
    high_threshold=0.174,
    medium_threshold=0.08,
    margin_step=1,
    home_label="Home-field",
    season_regression=0.5,
    starting_rating=1500.0,
)


def predict_game(
    game: Game,
    ratings: Mapping[str, float],
    rng: random.Random,
    *,
    model: SportModel = NFL,
    n_simulations: int = N_SIMULATIONS,
) -> StatsPrediction:
    """Predict one game from pre-game `ratings`; neutral sites get no home advantage.
    A team missing from `ratings` (no game played yet) starts at `starting_rating`."""
    table = dict(ratings)
    for team in (game.home, game.away):
        table.setdefault(team, model.starting_rating)
    return predict_match(
        game.home, game.away, table, model.home_advantage, n_simulations, rng,
        model=model, neutral=game.neutral,
    )
