"""Golden characterisation snapshot of the NRL stats model (common/stats_model/).

Committed on unmodified `main` *before* the SportModel adapter refactor (NFL
predictor spec, .claude/sdlc/nfl-predictor/spec.md, Phase 1 criterion 1.1), so
the refactor can prove NRL behaviour is byte-identical: every `predict_match`,
`simulate_match`, `update_ratings`, `confidence_for` and `compute_ratings_as_of`
output below must equal tests/fixtures/stats_model_nrl_golden.json exactly.

The fixture stores each case's inputs alongside its expected output, so other
tests (e.g. tests/common/test_sport.py) can replay the same cases. Never
regenerate it to make a refactor pass — a diff here *is* an NRL behaviour
change. Regenerate only for a deliberate, reviewed model change:

    .venv/bin/python -m tests.common.test_stats_model_nrl_golden --write
"""
from __future__ import annotations

import dataclasses
import json
import random
import sys
from pathlib import Path

from common.stats_model.confidence import confidence_for
from common.stats_model.elo import update_ratings
from common.stats_model.predictor import predict_match
from common.stats_model.ratings import compute_ratings_as_of
from common.stats_model.simulate import simulate_match

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "stats_model_nrl_golden.json"

# (home, away, home_rating, away_rating, home_advantage, n_simulations, seed,
#  home_rating_adjustment, away_rating_adjustment, margin_stdev_multiplier)
_PREDICT_CASES = [
    ("panthers", "broncos", 1500.0, 1500.0, 55.0, 2000, 1, 0.0, 0.0, 1.0),
    ("panthers", "broncos", 1500.0, 1500.0, 0.0, 2000, 2, 0.0, 0.0, 1.0),
    ("panthers", "broncos", 1650.0, 1350.0, 55.0, 2000, 3, 0.0, 0.0, 1.0),
    ("panthers", "broncos", 1350.0, 1650.0, 55.0, 2000, 4, 0.0, 0.0, 1.0),
    ("storm", "roosters", 1520.0, 1480.0, 55.0, 2000, 5, 0.0, 0.0, 1.4),
    ("storm", "roosters", 1480.0, 1530.0, 55.0, 2000, 6, -40.0, 0.0, 1.0),
    ("storm", "roosters", 1510.0, 1505.0, 55.0, 2000, 7, 0.0, 25.0, 1.0),
    ("sharks", "raiders", 1560.0, 1440.0, 55.0, 2000, 8, 15.0, -30.0, 1.4),
    ("sharks", "raiders", 1490.0, 1500.0, 55.0, 2000, 9, 0.0, 0.0, 1.0),
    ("dolphins", "titans", 1600.0, 1570.0, 55.0, 10000, 10, 0.0, 0.0, 1.0),
    ("dolphins", "titans", 1440.0, 1600.0, 55.0, 2000, 11, 0.0, -20.0, 1.4),
    ("eels", "dragons", 1700.0, 1400.0, 55.0, 5000, 12, 0.0, 0.0, 1.4),
]

# (home_rating, away_rating, home_advantage, n, seed, margin_stdev_multiplier)
_SIMULATE_CASES = [
    (1500.0, 1500.0, 55.0, 2000, 1, 1.0),
    (1500.0, 1500.0, 0.0, 2000, 2, 1.0),
    (1650.0, 1350.0, 55.0, 2000, 3, 1.0),
    (1350.0, 1650.0, 55.0, 2000, 4, 1.4),
    (1520.0, 1480.0, 55.0, 5000, 5, 0.7),
    (1480.0, 1555.0, 55.0, 2000, 6, 1.0),
]

# (home_rating, away_rating, home_score, away_score, home_advantage, k_factor)
_UPDATE_CASES = [
    (1500.0, 1500.0, 24, 12, 55.0, 20.0),
    (1500.0, 1500.0, 12, 24, 55.0, 20.0),
    (1500.0, 1500.0, 18, 18, 55.0, 20.0),
    (1650.0, 1350.0, 40, 0, 55.0, 20.0),
    (1350.0, 1650.0, 20, 18, 0.0, 32.0),
]

_CONFIDENCE_CASES = [0.0, 0.3, 0.38, 0.44, 0.5, 0.53, 0.56, 0.62, 0.7, 1.0]

# ~20 synthetic results rows: a tie, a display-name team (exercises to_slug), a
# legacy unqualified matchId (skipped), and rounds at/after each cut-off.
_RESULTS = [
    ("round-1-panthers-v-broncos", "panthers", "broncos", 24, 12),
    ("round-1-storm-v-roosters", "storm", "roosters", 18, 20),
    ("round-1-sharks-v-raiders", "sharks", "raiders", 30, 6),
    ("round-2-broncos-v-storm", "broncos", "storm", 16, 16),
    ("round-2-roosters-v-sharks", "roosters", "sharks", 22, 10),
    ("round-2-raiders-v-panthers", "raiders", "panthers", 4, 36),
    ("round-3-panthers-v-storm", "Penrith Panthers", "storm", 12, 14),
    ("round-3-sharks-v-broncos", "sharks", "broncos", 26, 24),
    ("round-3-roosters-v-raiders", "roosters", "raiders", 44, 0),
    ("panthers-v-roosters", "panthers", "roosters", 60, 0),
    ("round-4-storm-v-sharks", "storm", "sharks", 20, 8),
    ("round-4-broncos-v-roosters", "broncos", "roosters", 10, 32),
    ("round-4-raiders-v-panthers", "raiders", "panthers", 19, 18),
    ("round-5-panthers-v-sharks", "panthers", "sharks", 28, 6),
    ("round-5-storm-v-raiders", "storm", "raiders", 34, 12),
    ("round-5-roosters-v-broncos", "roosters", "broncos", 14, 20),
    ("round-6-broncos-v-raiders", "broncos", "raiders", 22, 22),
    ("round-6-sharks-v-storm", "sharks", "storm", 6, 30),
    ("round-6-panthers-v-roosters", "panthers", "roosters", 38, 10),
    ("round-7-raiders-v-roosters", "raiders", "roosters", 16, 12),
]

_RATINGS_CUTOFFS = [(1, 55.0), (3, 55.0), (5, 55.0), (8, 55.0), (8, 0.0)]


def _results_rows() -> list[dict]:
    return [
        {"matchId": m, "homeTeam": h, "awayTeam": a, "homeScore": hs, "awayScore": as_}
        for m, h, a, hs, as_ in _RESULTS
    ]


def _snapshot() -> dict:
    """Run every case against the current code and return inputs + outputs."""
    predict = []
    for (home, away, hr, ar, adv, n, seed, h_adj, a_adj, mult) in _PREDICT_CASES:
        inputs = {
            "home": home, "away": away, "ratings": {home: hr, away: ar},
            "home_advantage": adv, "n_simulations": n, "seed": seed,
            "home_rating_adjustment": h_adj, "away_rating_adjustment": a_adj,
            "margin_stdev_multiplier": mult,
        }
        pred = predict_match(
            home, away, {home: hr, away: ar}, adv, n, random.Random(seed),
            home_rating_adjustment=h_adj, away_rating_adjustment=a_adj,
            margin_stdev_multiplier=mult,
        )
        predict.append({"inputs": inputs, "expected": dataclasses.asdict(pred)})

    simulate = []
    for (hr, ar, adv, n, seed, mult) in _SIMULATE_CASES:
        inputs = {
            "home_rating": hr, "away_rating": ar, "home_advantage": adv,
            "n": n, "seed": seed, "margin_stdev_multiplier": mult,
        }
        sim = simulate_match(hr, ar, adv, n, random.Random(seed), margin_stdev_multiplier=mult)
        simulate.append({"inputs": inputs, "expected": dataclasses.asdict(sim)})

    update = []
    for (hr, ar, hs, as_, adv, k) in _UPDATE_CASES:
        inputs = {
            "home_rating": hr, "away_rating": ar, "home_score": hs, "away_score": as_,
            "home_advantage": adv, "k_factor": k,
        }
        new = update_ratings(hr, ar, hs, as_, home_advantage=adv, k_factor=k)
        update.append({"inputs": inputs, "expected": list(new)})

    confidence = [
        {"inputs": {"win_probability": p}, "expected": confidence_for(p)}
        for p in _CONFIDENCE_CASES
    ]

    ratings = []
    for before_round, adv in _RATINGS_CUTOFFS:
        out = compute_ratings_as_of(_results_rows(), before_round, adv)
        ratings.append({
            "inputs": {"before_round": before_round, "home_advantage": adv},
            "expected": dict(sorted(out.items())),
        })

    return {
        "predict_match": predict,
        "simulate_match": simulate,
        "update_ratings": update,
        "confidence_for": confidence,
        "compute_ratings_as_of": {"results": _results_rows(), "cases": ratings},
    }


def _golden() -> dict:
    return json.loads(FIXTURE.read_text())


def test_predict_match_matches_golden():
    assert _snapshot()["predict_match"] == _golden()["predict_match"]


def test_simulate_match_matches_golden():
    assert _snapshot()["simulate_match"] == _golden()["simulate_match"]


def test_update_ratings_matches_golden():
    assert _snapshot()["update_ratings"] == _golden()["update_ratings"]


def test_confidence_for_matches_golden():
    assert _snapshot()["confidence_for"] == _golden()["confidence_for"]


def test_compute_ratings_as_of_matches_golden():
    assert _snapshot()["compute_ratings_as_of"] == _golden()["compute_ratings_as_of"]


def test_golden_covers_the_spec_cases():
    """Guard the fixture itself against being trimmed: criterion 1.1 asks for ~12
    predict cases incl. equal ratings, a 300-pt gap, non-zero adjustments and both
    stdev multipliers, plus a ~20-row results replay."""
    golden = _golden()
    cases = [c["inputs"] for c in golden["predict_match"]]
    assert len(cases) >= 12
    assert any(len(set(c["ratings"].values())) == 1 for c in cases)
    assert any(abs(max(c["ratings"].values()) - min(c["ratings"].values())) == 300 for c in cases)
    assert any(c["home_rating_adjustment"] for c in cases)
    assert any(c["away_rating_adjustment"] for c in cases)
    assert {c["margin_stdev_multiplier"] for c in cases} >= {1.0, 1.4}
    assert len(golden["compute_ratings_as_of"]["results"]) >= 20


if __name__ == "__main__":  # pragma: no cover — fixture regeneration helper
    if "--write" not in sys.argv:
        sys.exit("refusing to overwrite the golden fixture without --write")
    FIXTURE.write_text(json.dumps(_snapshot(), indent=2, sort_keys=True) + "\n")
    print(f"wrote {FIXTURE}")
