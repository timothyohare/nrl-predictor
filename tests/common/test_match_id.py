"""Tests for the canonical matchId helper (common/match_id.py)."""
import pytest

from common.match_id import (
    is_canonical,
    match_id,
    match_id_from_url,
    round_number_from_title,
    round_of,
    teams_of,
)


@pytest.mark.parametrize("url,expected", [
    ("/draw/nrl-premiership/2026/round-11/panthers-v-broncos/", "round-11-panthers-v-broncos"),
    ("/draw/nrl-premiership/2026/round-11/panthers-v-broncos", "round-11-panthers-v-broncos"),
    ("https://www.nrl.com/draw/nrl-premiership/2026/round-3/sea-eagles-v-storm/", "round-3-sea-eagles-v-storm"),
    # Finals URLs use non-numeric segments — translated onto the same round-qualified
    # numbering as regular rounds (27 regular rounds, so Finals Week 1 = round 28) so
    # is_canonical()/round_of() keep working for finals matchIds too. Previously this
    # produced "finals-week-1-eels-v-storm" — not round-prefixed at all.
    ("/draw/nrl/2026/finals-week-1/eels-v-storm/", "round-28-eels-v-storm"),
    ("/draw/nrl/2026/finals-week-2/eels-v-storm/", "round-29-eels-v-storm"),
    ("/draw/nrl/2026/finals-week-3/eels-v-storm/", "round-30-eels-v-storm"),
    ("/draw/nrl/2026/grand-final/eels-v-storm/", "round-31-eels-v-storm"),
])
def test_match_id_from_url(url, expected):
    assert match_id_from_url(url) == expected


@pytest.mark.parametrize("title,expected", [
    ("Round 1", (1, False)),
    ("Round 27", (27, False)),
    ("Finals Week 1", (28, True)),
    ("Finals Week 2", (29, True)),
    ("Finals Week 3", (30, True)),
    ("Grand Final", (31, True)),
])
def test_round_number_from_title(title, expected):
    assert round_number_from_title(title) == expected


def test_round_number_from_title_rejects_unrecognised_format():
    with pytest.raises(ValueError):
        round_number_from_title("Preliminary Semi Final")


def test_match_id_from_fields_slugs_but_keeps_order():
    assert match_id(16, "Manly Sea Eagles", "Melbourne Storm") == "round-16-sea-eagles-v-storm"
    # home/away order is preserved (the draw decides it) — not alphabetised
    assert match_id(16, "Storm", "Sea Eagles") == "round-16-storm-v-sea-eagles"


def test_match_id_from_url_single_segment_falls_back():
    # a bare slug (no path) falls back to the last segment untouched
    assert match_id_from_url("panthers-v-broncos") == "panthers-v-broncos"
    assert match_id_from_url("panthers-v-broncos/") == "panthers-v-broncos"


def test_is_canonical_and_round_of():
    assert is_canonical("round-16-knights-v-dragons")
    assert not is_canonical("knights-v-dragons")
    assert round_of("round-17-sea-eagles-v-storm") == 17
    assert round_of("sea-eagles-v-storm") is None


def test_is_canonical_and_round_of_tolerate_empty():
    assert is_canonical("") is False
    assert is_canonical(None) is False
    assert round_of("") is None
    assert round_of(None) is None


def test_teams_of_splits_round_qualified_id():
    assert teams_of("round-17-sea-eagles-v-storm") == ("sea-eagles", "storm")
    assert teams_of("round-24-wests-tigers-v-dragons") == ("wests-tigers", "dragons")


def test_teams_of_handles_legacy_unqualified_id():
    assert teams_of("panthers-v-broncos") == ("panthers", "broncos")


def test_teams_of_tolerates_bad_input():
    assert teams_of("not-a-match-id") is None
    assert teams_of("") is None
    assert teams_of(None) is None
