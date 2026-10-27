"""Thin CLI scripts/nfl_backfill.py over nfl/orchestrator/backfill.py (kept beside
the orchestrator tests to share their moto fixtures)."""
from __future__ import annotations

from datetime import datetime

from nfl.orchestrator import lambda_handler
from scripts import nfl_backfill
from tests.nfl.orchestrator.conftest import BEFORE_WEEK_8, scan


def test_dry_run_lists_and_writes_nothing(tables, monkeypatch, capsys):
    monkeypatch.setattr(lambda_handler, "_now", lambda: datetime.fromisoformat(BEFORE_WEEK_8))
    assert nfl_backfill.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "nfl-2026-week-5-commanders-v-giants" in out
    assert "dry run" in out.lower()
    assert scan(tables.predictions) == []


def test_writes_labelled_rows(tables, monkeypatch, capsys):
    monkeypatch.setattr(lambda_handler, "_now", lambda: datetime.fromisoformat(BEFORE_WEEK_8))
    assert nfl_backfill.main(["--through-week", "5"]) == 0
    rows = scan(tables.predictions)
    assert [r["matchId"] for r in rows] == ["nfl-2026-week-5-commanders-v-giants"]
    assert rows[0]["backfilled"] is True
