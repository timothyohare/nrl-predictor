"""NFL predictor: team/match identity, nflverse schedule parsing, the fitted NFL
SportModel and the walk-forward backtest. See .claude/sdlc/nfl-predictor/spec.md.

Kept apart from the NRL identity modules (common/teams.py, common/match_id.py) on
purpose: the two registries share slugs ("broncos", "panthers", "cowboys",
"dolphins") that mean different clubs, so they must never be mixed.
"""
