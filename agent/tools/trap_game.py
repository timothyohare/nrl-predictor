"""Trap game detection — identifies schedule context that favours upsets."""

import os
import boto3

# Minimum round for dead rubber detection (late season)
_DEAD_RUBBER_MIN_ROUND = 18
# Trap game threshold
_TRAP_THRESHOLD = 2.0


def _get_ladder_positions(season: int, teams_table) -> dict[str, int]:
    """Return {team_name: position} from the ladder."""
    response = teams_table.get_item(Key={"teamId": f"ladder#{season}", "round": "current"})
    item = response.get("Item")
    if not item:
        return {}
    return {p["team"]: int(p["position"]) for p in item.get("positions", [])}


def _find_team_fixture(team: str, round_number: int, teams_table) -> dict | None:
    """Find the draw entry for a team in a specific round by scanning."""
    response = teams_table.scan(
        FilterExpression="round = :r AND team = :t",
        ExpressionAttributeValues={":r": str(round_number), ":t": team},
    )
    items = response.get("Items", [])
    return items[0] if items else None


def _get_previous_result(team: str, results_table) -> dict | None:
    """Get the most recent result involving this team."""
    response = results_table.scan(
        FilterExpression="homeTeam = :t OR awayTeam = :t",
        ExpressionAttributeValues={":t": team},
    )
    items = response.get("Items", [])
    if not items:
        return None
    items.sort(key=lambda x: x.get("scoredAt", ""), reverse=True)
    return items[0]


def _get_earlier_meetings(home_team: str, away_team: str, current_match_id: str, results_table) -> list[dict]:
    """Get earlier results between these two teams this season."""
    response = results_table.scan(
        FilterExpression="(homeTeam = :a AND awayTeam = :b) OR (homeTeam = :b AND awayTeam = :a)",
        ExpressionAttributeValues={":a": home_team, ":b": away_team},
    )
    items = response.get("Items", [])
    # Exclude current match if it somehow exists
    return [i for i in items if i.get("matchId") != current_match_id]


def _check_sandwich(team: str, round_number: int, ladder: dict, teams_table, results_table) -> dict | None:
    """Check if team is sandwiched between two tough opponents."""
    if round_number <= 1:
        return None

    prev_fixture = _find_team_fixture(team, round_number - 1, teams_table)
    next_fixture = _find_team_fixture(team, round_number + 1, teams_table)

    if not prev_fixture or not next_fixture:
        return None

    # Determine the opponents
    prev_match_id = prev_fixture.get("matchId", "")
    next_match_id = next_fixture.get("matchId", "")

    # Find the opponent from the other side of each fixture
    prev_opponent = _get_opponent_from_fixture(team, prev_match_id, teams_table)
    next_opponent = _get_opponent_from_fixture(team, next_match_id, teams_table)

    if not prev_opponent or not next_opponent:
        return None

    prev_pos = ladder.get(prev_opponent, 17)
    next_pos = ladder.get(next_opponent, 17)

    # Both adjacent opponents must be top-4
    if prev_pos <= 4 and next_pos <= 4:
        return {
            "type": "sandwich_game",
            "points": 1.5,
            "detail": f"{team} played {prev_opponent} ({prev_pos}{_ordinal(prev_pos)}) last round, faces {next_opponent} ({next_pos}{_ordinal(next_pos)}) next round",
        }
    return None


def _get_opponent_from_fixture(team: str, match_id: str, teams_table) -> str | None:
    """Find the opponent team name from draw entries for a match."""
    for side in ("home", "away"):
        response = teams_table.get_item(Key={"teamId": f"{match_id}#{side}", "round": "0"})
        # Round might vary, so scan instead
    response = teams_table.scan(
        FilterExpression="matchId = :m",
        ExpressionAttributeValues={":m": match_id},
    )
    items = response.get("Items", [])
    for item in items:
        if item.get("team") != team:
            return item.get("team")
    return None


def _check_emotional_letdown(team: str, results_table) -> dict | None:
    """Check if team won last game by 20+ points."""
    last_result = _get_previous_result(team, results_table)
    if not last_result:
        return None

    winner = last_result.get("winner")
    margin = int(last_result.get("margin", 0))

    if winner == team and margin >= 20:
        loser = last_result["awayTeam"] if last_result["homeTeam"] == team else last_result["homeTeam"]
        return {
            "type": "emotional_letdown",
            "points": 1.0,
            "detail": f"{team} won last game by {margin} points (beat {loser} {last_result.get('homeScore', 0)}-{last_result.get('awayScore', 0)})",
        }
    return None


def _check_dead_rubber(favourite: str, underdog: str, round_number: int, ladder: dict) -> dict | None:
    """Check if favourite has nothing to play for while underdog is fighting for finals."""
    if round_number < _DEAD_RUBBER_MIN_ROUND:
        return None

    fav_pos = ladder.get(favourite, 17)
    dog_pos = ladder.get(underdog, 17)

    # Favourite locked in top-4, underdog in 7th-10th (fighting for 8th)
    if fav_pos <= 4 and 7 <= dog_pos <= 10:
        return {
            "type": "dead_rubber",
            "points": 1.5,
            "detail": f"{favourite} ({fav_pos}{_ordinal(fav_pos)}) has top-4 secured; {underdog} ({dog_pos}{_ordinal(dog_pos)}) fighting for finals spot",
        }
    return None


def _check_revenge(home_team: str, away_team: str, match_id: str, ladder: dict, results_table) -> dict | None:
    """Check if the underdog lost a close game earlier this season."""
    fav_pos = ladder.get(home_team, 17)
    dog_pos = ladder.get(away_team, 17)
    favourite = home_team if fav_pos < dog_pos else away_team
    underdog = away_team if favourite == home_team else home_team

    meetings = _get_earlier_meetings(home_team, away_team, match_id, results_table)
    if not meetings:
        return None

    for m in meetings:
        winner = m.get("winner")
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

    ladder = _get_ladder_positions(season, t_tbl)

    # Determine favourite based on ladder position
    home_pos = ladder.get(home_team, 17)
    away_pos = ladder.get(away_team, 17)
    favourite = home_team if home_pos < away_pos else away_team
    underdog = away_team if favourite == home_team else home_team

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
    revenge = _check_revenge(home_team, away_team, match_id, ladder, r_tbl)
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
