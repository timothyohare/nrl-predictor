"""Trap game detection — identifies schedule context that favours upsets.

Team names arrive from three different sources with three different casings:
tool-call args (nickname, e.g. "Panthers"), draw/team-sheet rows in the
``teams`` table (nickname, e.g. "Panthers" in ``homeTeam``/``awayTeam``), and
the ``results`` table + ladder ``positions`` rows (canonical slug, e.g.
"panthers" — written via ``to_slug()`` at scrape time). Every comparison in
this module normalises to slug form at the point of use so all three line up.
"""

import os

import boto3

from common.teams import to_slug

# Minimum round for dead rubber detection (late season)
_DEAD_RUBBER_MIN_ROUND = 18
# Trap game threshold
_TRAP_THRESHOLD = 2.0


def _get_ladder_positions(season: int, teams_table) -> dict[str, int]:
    """Return {team_slug: position} from the ladder."""
    response = teams_table.get_item(Key={"teamId": f"ladder#{season}", "round": "current"})
    item = response.get("Item")
    if not item:
        return {}
    return {to_slug(p["team_name"]): int(p["position"]) for p in item.get("positions", [])}


def _find_team_fixture(team_slug: str, round_number: int, teams_table) -> dict | None:
    """Find the draw/team-sheet row for a team in a specific round.

    Rows are one per match — keyed ``teamId=matchId``, ``round=str(round_number)``,
    with nickname-cased ``homeTeam``/``awayTeam`` fields (the same schema
    ``get_team_sheet`` reads). Scan the round, match client-side on slug —
    mirroring ``recent_form.py``'s scan-then-slug-filter pattern, since the
    stored casing can't be matched with a DynamoDB-side expression.
    """
    response = teams_table.scan(
        FilterExpression="#r = :r",
        ExpressionAttributeNames={"#r": "round"},
        ExpressionAttributeValues={":r": str(round_number)},
    )
    for item in response.get("Items", []):
        if team_slug in (to_slug(item.get("homeTeam", "")), to_slug(item.get("awayTeam", ""))):
            return item
    return None


def _opponent_from_fixture(team_slug: str, fixture: dict) -> str | None:
    """Given a fixture row already known to contain this team, return the
    other side's slug."""
    home, away = to_slug(fixture.get("homeTeam", "")), to_slug(fixture.get("awayTeam", ""))
    if home == team_slug:
        return away
    if away == team_slug:
        return home
    return None


def _get_previous_result(team_slug: str, results_table) -> dict | None:
    """Get the most recent result involving this team."""
    items = [
        i for i in results_table.scan().get("Items", [])
        if team_slug in (to_slug(i.get("homeTeam", "")), to_slug(i.get("awayTeam", "")))
    ]
    if not items:
        return None
    items.sort(key=lambda x: x.get("scoredAt", ""), reverse=True)
    return items[0]


def _get_earlier_meetings(home_slug: str, away_slug: str, current_match_id: str, results_table) -> list[dict]:
    """Get earlier results between these two teams this season."""
    pair = {home_slug, away_slug}
    items = [
        i for i in results_table.scan().get("Items", [])
        if {to_slug(i.get("homeTeam", "")), to_slug(i.get("awayTeam", ""))} == pair
    ]
    # Exclude current match if it somehow exists
    return [i for i in items if i.get("matchId") != current_match_id]


def _check_sandwich(team_slug: str, round_number: int, ladder: dict, teams_table, results_table) -> dict | None:
    """Check if team is sandwiched between two tough opponents."""
    if round_number <= 1:
        return None

    prev_fixture = _find_team_fixture(team_slug, round_number - 1, teams_table)
    next_fixture = _find_team_fixture(team_slug, round_number + 1, teams_table)

    if not prev_fixture or not next_fixture:
        return None

    prev_opponent = _opponent_from_fixture(team_slug, prev_fixture)
    next_opponent = _opponent_from_fixture(team_slug, next_fixture)

    if not prev_opponent or not next_opponent:
        return None

    prev_pos = ladder.get(prev_opponent, 17)
    next_pos = ladder.get(next_opponent, 17)

    # Both adjacent opponents must be top-4
    if prev_pos <= 4 and next_pos <= 4:
        return {
            "type": "sandwich_game",
            "points": 1.5,
            "detail": f"{team_slug} played {prev_opponent} ({prev_pos}{_ordinal(prev_pos)}) last round, faces {next_opponent} ({next_pos}{_ordinal(next_pos)}) next round",
        }
    return None


def _check_emotional_letdown(team_slug: str, results_table) -> dict | None:
    """Check if team won last game by 20+ points."""
    last_result = _get_previous_result(team_slug, results_table)
    if not last_result:
        return None

    winner = to_slug(last_result.get("winner", ""))
    margin = int(last_result.get("margin", 0))

    if winner == team_slug and margin >= 20:
        home = to_slug(last_result.get("homeTeam", ""))
        loser = last_result["awayTeam"] if home == team_slug else last_result["homeTeam"]
        return {
            "type": "emotional_letdown",
            "points": 1.0,
            "detail": f"{team_slug} won last game by {margin} points (beat {loser} {last_result.get('homeScore', 0)}-{last_result.get('awayScore', 0)})",
        }
    return None


def _check_dead_rubber(favourite_slug: str, underdog_slug: str, round_number: int, ladder: dict) -> dict | None:
    """Check if favourite has nothing to play for while underdog is fighting for finals."""
    if round_number < _DEAD_RUBBER_MIN_ROUND:
        return None

    fav_pos = ladder.get(favourite_slug, 17)
    dog_pos = ladder.get(underdog_slug, 17)

    # Favourite locked in top-4, underdog in 7th-10th (fighting for 8th)
    if fav_pos <= 4 and 7 <= dog_pos <= 10:
        return {
            "type": "dead_rubber",
            "points": 1.5,
            "detail": f"{favourite_slug} ({fav_pos}{_ordinal(fav_pos)}) has top-4 secured; {underdog_slug} ({dog_pos}{_ordinal(dog_pos)}) fighting for finals spot",
        }
    return None


def _check_revenge(home_slug: str, away_slug: str, match_id: str, ladder: dict, results_table) -> dict | None:
    """Check if the underdog lost a close game earlier this season."""
    fav_pos = ladder.get(home_slug, 17)
    dog_pos = ladder.get(away_slug, 17)
    favourite = home_slug if fav_pos < dog_pos else away_slug
    underdog = away_slug if favourite == home_slug else home_slug

    meetings = _get_earlier_meetings(home_slug, away_slug, match_id, results_table)
    if not meetings:
        return None

    for m in meetings:
        winner = to_slug(m.get("winner", ""))
        margin = int(m.get("margin", 0))
        if winner == favourite and margin < 8:
            return {
                "type": "revenge_game",
                "points": 0.5,
                "detail": f"{underdog} lost to {favourite} by {margin} earlier this season — revenge motivation",
            }
    return None


def _ordinal(n: int) -> str:
    if 11 <= (n % 100) <= 13:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def detect_trap_game(
    match_id: str,
    round_number: int,
    season: int,
    home_team: str,
    away_team: str,
    teams_table=None,
    results_table=None,
) -> dict:
    """Analyse schedule context for trap game indicators."""
    t_tbl = teams_table or boto3.resource("dynamodb").Table(os.environ["TEAMS_TABLE"])
    r_tbl = results_table or boto3.resource("dynamodb").Table(os.environ["RESULTS_TABLE"])

    # Slug at the boundary — ladder/results already store slugs, draw rows
    # store nickname casing, so every internal comparison works in slug form.
    home_slug = to_slug(home_team)
    away_slug = to_slug(away_team)

    ladder = _get_ladder_positions(season, t_tbl)

    # Determine favourite based on ladder position
    home_pos = ladder.get(home_slug, 17)
    away_pos = ladder.get(away_slug, 17)
    favourite = home_slug if home_pos < away_pos else away_slug
    underdog = away_slug if favourite == home_slug else home_slug

    indicators = []

    # 1. Sandwich game — favourite between two tough opponents
    sandwich = _check_sandwich(favourite, round_number, ladder, t_tbl, r_tbl)
    if sandwich:
        indicators.append(sandwich)

    # 2. Emotional letdown — favourite won big last game
    letdown = _check_emotional_letdown(favourite, r_tbl)
    if letdown:
        indicators.append(letdown)

    # 3. Dead rubber — favourite has nothing to play for
    dead = _check_dead_rubber(favourite, underdog, round_number, ladder)
    if dead:
        indicators.append(dead)

    # 4. Revenge game — underdog lost close one earlier
    revenge = _check_revenge(home_slug, away_slug, match_id, ladder, r_tbl)
    if revenge:
        indicators.append(revenge)

    trap_score = sum(i["points"] for i in indicators)
    is_trap = trap_score >= _TRAP_THRESHOLD

    result = {
        "trap_score": round(trap_score, 1),
        "is_trap_game": is_trap,
        "indicators": indicators,
        "favourite": favourite,
        "underdog": underdog,
    }

    if is_trap:
        result["recommendation"] = (
            f"Consider downgrading {favourite} confidence. "
            f"Trap score {trap_score:.1f}/5."
        )

    return result
