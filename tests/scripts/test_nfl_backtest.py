"""CLI wrapper scripts/nfl_backtest.py — spec criteria 2.11 and the exit-code
contract behind 2.12/2.13. The logic lives in common/nfl/backtest.py."""
from __future__ import annotations

import json
from pathlib import Path

from scripts import nfl_backtest

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "nfl_games_sample.csv"
BASE_ARGS = ["--csv", str(FIXTURE), "--eval-from", "2020", "--eval-to", "2025", "--simulations", "200"]


def test_json_output_has_the_spec_keys(tmp_path, capsys):
    out = tmp_path / "bt.json"
    assert nfl_backtest.main([*BASE_ARGS, "--json", str(out)]) == 0
    report = json.loads(out.read_text())
    assert set(report) >= {"data_sha256", "fit_window", "eval_window", "params", "overall",
                           "per_season", "baselines", "by_confidence", "calibration_bins"}
    assert set(report["baselines"]) == {"home", "market"}
    assert set(report["overall"]) >= {"n", "accuracy", "brier", "margin_mae"}
    printed = capsys.readouterr().out
    assert "model" in printed and "home" in printed and "market" in printed


def test_enforce_bar_exit_code_follows_check_bar(monkeypatch, capsys):
    monkeypatch.setattr(nfl_backtest.backtest, "check_bar", lambda report: ["accuracy too low"])
    assert nfl_backtest.main([*BASE_ARGS, "--enforce-bar"]) == 1
    assert "accuracy too low" in capsys.readouterr().out
    monkeypatch.setattr(nfl_backtest.backtest, "check_bar", lambda report: [])
    assert nfl_backtest.main([*BASE_ARGS, "--enforce-bar"]) == 0


def test_without_enforce_bar_a_miss_still_exits_zero(monkeypatch):
    monkeypatch.setattr(nfl_backtest.backtest, "check_bar", lambda report: ["miss"])
    assert nfl_backtest.main(BASE_ARGS) == 0


def test_fit_only_compares_against_the_committed_constants(monkeypatch, capsys):
    # The fixture's fit is not the committed full-CSV fit -> mismatch -> non-zero.
    assert nfl_backtest.main([*BASE_ARGS, "--fit-only"]) == 1
    assert "differs" in capsys.readouterr().out
    fitted = nfl_backtest.backtest.fit(
        nfl_backtest.games_module.parse_csv(FIXTURE.read_text())[0], 2020
    )
    monkeypatch.setattr(nfl_backtest, "NFL", fitted)
    assert nfl_backtest.main([*BASE_ARGS, "--fit-only"]) == 0
