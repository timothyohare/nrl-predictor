from __future__ import annotations

from pathlib import Path

import pytest

FIXTURE_CSV = Path(__file__).resolve().parents[2] / "fixtures" / "nfl_games_sample.csv"


@pytest.fixture
def sample_csv_text() -> str:
    return FIXTURE_CSV.read_text()
