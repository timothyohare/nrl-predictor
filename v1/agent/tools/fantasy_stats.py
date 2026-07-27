import re

import requests

from common.teams import display, to_slug

_BASE = "https://fantasy.nrl.com/data/nrl"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:148.0) Gecko/20100101 Firefox/148.0",
    "Referer": "https://fantasy.nrl.com/stats-centre",
}
_UNAVAILABLE_STATUSES = {"injured", "not-playing", "suspended"}
_UNCERTAIN_STATUSES = {"uncertain"}
_PRICE_DROP_THRESHOLD = -5.0  # percent

# Module-level cache: fetched once per Lambda invocation
_squads_cache: list | None = None
_players_cache: list | None = None


def _fetch_squads() -> list:
    global _squads_cache
    if _squads_cache is None:
        r = requests.get(f"{_BASE}/squads.json", headers=_HEADERS, timeout=10)
        r.raise_for_status()
        _squads_cache = r.json()
    return _squads_cache


def _fetch_players() -> list:
    global _players_cache
    if _players_cache is None:
        r = requests.get(f"{_BASE}/players.json", headers=_HEADERS, timeout=10)
        r.raise_for_status()
        _players_cache = r.json()
    return _players_cache


def _normalise(s: str) -> str:
    """Strip everything but letters/digits, so hyphens, spaces, and stray
    punctuation ("St George" vs the API's "St. George") don't cause a miss."""
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _squad_id_for(team: str, squads: list) -> int | None:
    """Match against the fantasy API's own naming (e.g. "Tigers" /
    "Wests Tigers"), which uses spaces, not our hyphenated slugs — a raw
    slug like "sea-eagles" never appears verbatim in the API's data, so
    resolve to our registry's display names first and compare on those."""
    slug = to_slug(team)
    meta = display(slug)
    candidates = {_normalise(meta["nickname"]), _normalise(meta["full_name"]), _normalise(team)}
    for s in squads:
        if _normalise(s["name"]) in candidates or _normalise(s["full_name"]) in candidates:
            return s["id"]
    return None


def _peak_drop_pct(prices: dict) -> float | None:
    if not prices:
        return None
    sorted_rounds = sorted(prices, key=int)
    current = prices[sorted_rounds[-1]]
    peak = max(prices[r] for r in sorted_rounds)
    if peak == 0:
        return None
    return round((current - peak) / peak * 100, 1)


def get_fantasy_stats(team: str) -> dict:
    """Return availability and price-signal data for all players in a team.

    Returns a dict with:
      unavailable   — confirmed out (injured / not-playing / suspended)
      uncertain     — listed as uncertain for this round
      price_alerts  — playing players whose cost dropped >5% from peak
                      (early signal of undisclosed rest/injury)
    """
    squads = _fetch_squads()
    players = _fetch_players()

    squad_id = _squad_id_for(team, squads)
    if squad_id is None:
        return {"unavailable": [], "uncertain": [], "price_alerts": []}

    team_players = [p for p in players if p["squad_id"] == squad_id]

    unavailable = []
    uncertain = []
    price_alerts = []

    for p in team_players:
        status = p.get("status", "")
        name = f"{p['first_name']} {p['last_name']}"
        stats = p.get("stats") or {}
        entry = {
            "name": name,
            "status": status,
            "avg_points": stats.get("avg_points"),
            "last_3_avg": stats.get("last_3_avg"),
        }

        if status in _UNAVAILABLE_STATUSES:
            unavailable.append(entry)
        elif status in _UNCERTAIN_STATUSES:
            uncertain.append(entry)
        elif status == "playing":
            drop = _peak_drop_pct(stats.get("prices") or {})
            if drop is not None and drop < _PRICE_DROP_THRESHOLD:
                price_alerts.append({**entry, "price_drop_pct": drop})

    price_alerts.sort(key=lambda x: x["price_drop_pct"])

    return {
        "unavailable": unavailable,
        "uncertain": uncertain,
        "price_alerts": price_alerts,
    }
