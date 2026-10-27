"""Canonical NFL team identity — mirrors the `to_slug/is_known/display` API of
common/teams.py, over common/nfl/team_registry.json.

A franchise is *always* its lowercase current nickname ("chiefs", "49ers",
"commanders"). nflverse codes, full names and historical/relocated forms are
inbound aliases — SD->chargers, OAK->raiders, STL->rams — so Elo carries across a
relocation instead of resetting to the starting rating.
"""
from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

_REGISTRY_PATH = Path(__file__).with_name("team_registry.json")


def _normalise(name: str) -> str:
    """Lower-case, drop full stops, collapse separators so all inbound forms compare equal."""
    return re.sub(r"[\s\-_]+", " ", name.strip().lower().replace(".", "")).strip()


@lru_cache(maxsize=1)
def _registry() -> dict[str, dict]:
    return json.loads(_REGISTRY_PATH.read_text())


@lru_cache(maxsize=1)
def _lookup() -> dict[str, str]:
    """Map every known inbound form (normalised) -> slug."""
    table: dict[str, str] = {}
    for slug, meta in _registry().items():
        for form in (slug, meta["nickname"], meta["full_name"], meta["abbrev"], *meta["aliases"]):
            table[_normalise(form)] = slug
    return table


def to_slug(name: str) -> str:
    """Resolve any inbound team string to its canonical slug.

    Total and idempotent: unknown input is returned unchanged (with a warning).
    Every accepted form (code, nickname, full name, historical name) is an explicit
    registry entry — there is no fuzzy fallback.
    """
    if not name:
        return name
    norm = _normalise(name)
    slug = _lookup().get(norm)
    if slug:
        return slug
    logger.warning("nfl to_slug: unrecognised team name %r — passing through unchanged", name)
    return name


def is_known(name: str) -> bool:
    """True if ``name`` resolves to a registered franchise."""
    return to_slug(name) in _registry()


def all_slugs() -> list[str]:
    return list(_registry().keys())


def display(slug: str) -> dict:
    """Slug -> display metadata ({slug, nickname, full_name, abbrev}); an unknown
    slug echoes back so the UI degrades gracefully."""
    meta = _registry().get(slug)
    if not meta:
        return {"slug": slug, "nickname": slug, "full_name": slug, "abbrev": ""}
    return {"slug": slug, **{k: meta[k] for k in ("nickname", "full_name", "abbrev")}}


def display_name(slug: str) -> str:
    """Convenience: the short display name ("Chiefs") for a slug."""
    return display(slug)["nickname"]
