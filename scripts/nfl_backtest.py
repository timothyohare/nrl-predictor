#!/usr/bin/env python3
"""Walk-forward NFL backtest CLI — thin wrapper over common/nfl/backtest.py.
See .claude/sdlc/nfl-predictor/spec.md (Phase 2, criteria 2.11-2.13).

Fits the Elo constants on every season before --eval-from, then predicts each
--eval-from..--eval-to game from ratings as they stood before its week, and
prints model vs home-team baseline vs spread favourite (market: comparison
only, never model input).

Usage:
    .venv/bin/python scripts/nfl_backtest.py --csv games.csv --eval-from 2016 --eval-to 2025
    .venv/bin/python scripts/nfl_backtest.py --csv games.csv --eval-from 2016 --eval-to 2025 --enforce-bar
    .venv/bin/python scripts/nfl_backtest.py --csv games.csv --eval-from 2016 --fit-only

--csv takes a local path or an http(s) URL (e.g. the nflverse games.csv).
--enforce-bar exits 1 when the spec 2.12 success bar is missed.
--fit-only prints the fitted constants and exits 1 if they differ from the ones
committed in common/nfl/model.py.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

from common.nfl import backtest
from common.nfl import games as games_module
from common.nfl.model import N_SIMULATIONS, NFL


def _read(source: str) -> bytes:
    if source.startswith(("http://", "https://")):
        with urllib.request.urlopen(source, timeout=60) as resp:  # noqa: S310 — operator-supplied URL
            return resp.read()
    return Path(source).read_bytes()


def _fmt(value: float | None, digits: int = 3) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def _print_table(report: dict) -> None:
    home, market = report["baselines"]["home"], report["baselines"]["market"]
    print(f"data_sha256 {report['data_sha256']}")
    print(f"fit {report['fit_window']}  eval {report['eval_window']}  params {report['params']}")
    print()
    header = (
        f"{'season':>7} {'n':>4} | {'model acc':>9} {'brier':>6} {'mae':>6} | "
        f"{'home acc':>8} {'brier':>6} {'mae':>6} | {'market acc':>10} {'brier':>6} {'mae':>6}"
    )
    print(header)
    print("-" * len(header))
    rows = [(s, report["per_season"][s], home["per_season"][s], market["per_season"][s])
            for s in report["per_season"]]
    rows.append(("overall", report["overall"], home["overall"], market["overall"]))
    for label, m, h, k in rows:
        print(
            f"{label:>7} {m['n']:>4} | {_fmt(m['accuracy']):>9} {_fmt(m['brier']):>6} "
            f"{_fmt(m['margin_mae'], 2):>6} | {_fmt(h['accuracy']):>8} {_fmt(h['brier']):>6} "
            f"{_fmt(h['margin_mae'], 2):>6} | {_fmt(k['accuracy']):>10} {_fmt(k['brier']):>6} "
            f"{_fmt(k['margin_mae'], 2):>6}"
        )
    print()
    print("by_confidence (model):", {
        level: f"n={v['n']} acc={_fmt(v['accuracy'])}" for level, v in report["by_confidence"].items()
    })
    print("calibration (p_home bin -> n, mean_p, observed):")
    for b in report["calibration_bins"]:
        print(f"  {b['lo']:.1f}-{b['hi']:.1f}: n={b['n']:>4} "
              f"mean_p={_fmt(b['mean_p'])} observed={_fmt(b['home_win_rate'])}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--csv", required=True, help="nflverse games.csv path or URL")
    parser.add_argument("--eval-from", type=int, default=2016)
    parser.add_argument("--eval-to", type=int, default=2025)
    parser.add_argument("--json", help="write the full report as JSON to this path")
    parser.add_argument("--enforce-bar", action="store_true", help="exit 1 if the 2.12 bar is missed")
    parser.add_argument("--fit-only", action="store_true",
                        help="fit and compare with common/nfl/model.py, no evaluation")
    parser.add_argument("--simulations", type=int, default=N_SIMULATIONS)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)

    data = _read(args.csv)

    if args.fit_only:
        games, _ = games_module.parse_csv(data.decode("utf-8"))
        fitted = backtest.fit(games, args.eval_from)
        print(f"data_sha256 {hashlib.sha256(data).hexdigest()}")
        print(f"fit window: seasons < {args.eval_from}")
        print(json.dumps(dataclasses.asdict(fitted), indent=2))
        if fitted != NFL:
            print("fit differs from common/nfl/model.py NFL (committed):")
            print(json.dumps(dataclasses.asdict(NFL), indent=2))
            return 1
        print("fitted constants match common/nfl/model.py NFL")
        return 0

    result = backtest.run_backtest(
        data, args.eval_from, args.eval_to, n_simulations=args.simulations, seed=args.seed
    )
    _print_table(result.report)
    if args.json:
        Path(args.json).write_text(json.dumps(result.report, indent=2) + "\n")
        print(f"\nwrote {args.json}")

    failures = backtest.check_bar(result.report)
    print()
    if failures:
        print("BAR MISSED:")
        for failure in failures:
            print(f"  - {failure}")
    else:
        print("BAR MET (spec 2.12)")
    return 1 if args.enforce_bar and failures else 0


if __name__ == "__main__":
    sys.exit(main())
