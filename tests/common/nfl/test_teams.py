"""NFL team identity (common/nfl/teams.py) — spec criterion 2.1."""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest

from common.nfl import teams
from common.nfl.teams import all_slugs, display, display_name, is_known, to_slug

REGISTRY = Path(teams.__file__).with_name("team_registry.json")


def test_every_fixture_team_code_resolves(sample_csv_text):
    codes = set()
    for row in csv.DictReader(io.StringIO(sample_csv_text)):
        codes |= {row["home_team"], row["away_team"]}
    assert codes  # sanity: the fixture has teams
    for code in codes:
        assert is_known(code), code
        assert to_slug(code) in all_slugs()


def test_registry_has_exactly_32_franchises():
    assert len(all_slugs()) == 32
    assert len(json.loads(REGISTRY.read_text())) == 32


def test_slug_is_the_lowercased_current_nickname():
    for slug, meta in json.loads(REGISTRY.read_text()).items():
        assert slug == meta["nickname"].lower()
    assert {"chiefs", "49ers", "commanders"} <= set(all_slugs())


@pytest.mark.parametrize(
    ("old", "new", "slug"),
    [("SD", "LAC", "chargers"), ("OAK", "LV", "raiders"), ("STL", "LA", "rams")],
)
def test_relocated_franchises_share_one_slug(old, new, slug):
    assert to_slug(old) == to_slug(new) == slug


def test_all_nflverse_codes_resolve_to_distinct_current_franchises():
    codes = [
        "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN", "DET",
        "GB", "HOU", "IND", "JAX", "KC", "LA", "LAC", "LV", "MIA", "MIN", "NE", "NO",
        "NYG", "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WAS",
    ]
    assert sorted(to_slug(c) for c in codes) == sorted(all_slugs())


def test_to_slug_is_idempotent():
    for slug in all_slugs():
        assert to_slug(slug) == slug
        assert to_slug(to_slug(display(slug)["abbrev"])) == slug


@pytest.mark.parametrize(
    ("name", "slug"),
    [
        ("Kansas City Chiefs", "chiefs"),
        ("San Diego Chargers", "chargers"),
        ("Oakland Raiders", "raiders"),
        ("St. Louis Rams", "rams"),
        ("Washington Football Team", "commanders"),
        ("San Francisco 49ers", "49ers"),
        ("  new-england patriots ", "patriots"),
    ],
)
def test_full_and_historical_names_resolve(name, slug):
    assert to_slug(name) == slug


def test_unknown_name_passes_through_unchanged():
    assert to_slug("XYZ") == "XYZ"
    assert is_known("XYZ") is False
    assert to_slug("") == ""


def test_display_metadata():
    assert display("49ers") == {
        "slug": "49ers", "nickname": "49ers", "full_name": "San Francisco 49ers", "abbrev": "SF",
    }
    assert display_name("commanders") == "Commanders"
    assert display("nope") == {"slug": "nope", "nickname": "nope", "full_name": "nope", "abbrev": ""}
