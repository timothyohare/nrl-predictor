"""Spine synergy tool — analyses how many games a team's spine has played together."""

import os

import boto3

from common.teams import to_slug

_SPINE_NUMBERS = {1, 6, 7, 9}
_ESTABLISHED_THRESHOLD = 5


def _extract_spine(players: list[dict]) -> dict[int, str]:
    """Extract spine player last names by jersey number."""
    spine = {}
    for p in players:
        num = int(p.get("jersey_number", 0))
        if num in _SPINE_NUMBERS:
            spine[num] = p.get("last_name", "Unknown")
    return spine


def _get_historical_team_sheets(team: str, current_round: int, teams_table) -> list[dict]:
    """Get all team sheet entries where this team played, for rounds before current."""
    # Match on the canonical slug (robust to mixed nickname/slug storage); filter client-side.
    slug = to_slug(team)
    response = teams_table.scan(FilterExpression="attribute_exists(homePlayers)")
    results = []
    for item in response.get("Items", []):
        if slug not in (to_slug(item.get("homeTeam", "")), to_slug(item.get("awayTeam", ""))):
            continue
        try:
            rnd = int(item.get("round", "0"))
        except (ValueError, TypeError):
            continue
        if rnd < current_round:
            results.append(item)
    return results


def _get_result_for_match(match_id: str, results_table) -> dict | None:
    """Get the result for a specific match."""
    response = results_table.query(
        KeyConditionExpression="matchId = :m",
        ExpressionAttributeValues={":m": match_id},
        Limit=1,
    )
    items = response.get("Items", [])
    return items[0] if items else None


def _analyse_team(team: str, current_spine: dict[int, str], current_round: int,
                  teams_table, results_table) -> dict:
    """Analyse spine combination history for a team."""
    historical = _get_historical_team_sheets(team, current_round, teams_table)

    full_spine_games = 0
    full_spine_wins = 0
    halves_games = 0
    halves_wins = 0

    current_halves = {k: v for k, v in current_spine.items() if k in (6, 7)}

    for sheet in historical:
        # Determine which side this team is on
        if to_slug(sheet.get("homeTeam", "")) == to_slug(team):
            players = sheet.get("homePlayers", [])
        else:
            players = sheet.get("awayPlayers", [])

        hist_spine = _extract_spine(players)

        # Check full spine match
        full_match = all(
            hist_spine.get(num) == current_spine.get(num)
            for num in _SPINE_NUMBERS
        )

        # Check halves match
        halves_match = all(
            hist_spine.get(num) == current_halves.get(num)
            for num in (6, 7)
        )

        # Get result to compute win rate
        match_id = sheet.get("teamId", "")  # teamId = matchId for team sheet entries
        result = _get_result_for_match(match_id, results_table)
        won = to_slug(result.get("winner", "")) == to_slug(team) if result else False

        if full_match:
            full_spine_games += 1
            if won:
                full_spine_wins += 1

        if halves_match:
            halves_games += 1
            if won:
                halves_wins += 1

    is_established = full_spine_games >= _ESTABLISHED_THRESHOLD
    flags = []

    spine_names = "-".join(current_spine.get(n, "?") for n in sorted(_SPINE_NUMBERS))

    if not is_established:
        flags.append(
            f"Spine combination {spine_names} has only {full_spine_games} games together"
            f" (threshold: {_ESTABLISHED_THRESHOLD})"
        )

    if halves_games < _ESTABLISHED_THRESHOLD:
        halves_names = f"{current_spine.get(6, '?')}-{current_spine.get(7, '?')}"
        flags.append(
            f"Halves pairing {halves_names} is relatively new ({halves_games} games)"
        )

    return {
        "team": team,
        "spine": {
            "fullback": current_spine.get(1, "Unknown"),
            "five_eighth": current_spine.get(6, "Unknown"),
            "halfback": current_spine.get(7, "Unknown"),
            "hooker": current_spine.get(9, "Unknown"),
        },
        "full_spine_games_together": full_spine_games,
        "full_spine_win_rate": round(full_spine_wins / full_spine_games, 2) if full_spine_games > 0 else 0,
        "halves_games_together": halves_games,
        "halves_win_rate": round(halves_wins / halves_games, 2) if halves_games > 0 else 0,
        "is_established": is_established,
        "flags": flags,
    }


def get_spine_synergy(match_id: str, round_number: int, teams_table=None, results_table=None) -> dict:
    """Analyse spine combination experience for both teams in a match."""
    t_tbl = teams_table or boto3.resource("dynamodb").Table(os.environ["TEAMS_TABLE"])
    r_tbl = results_table or boto3.resource("dynamodb").Table(os.environ["RESULTS_TABLE"])

    # Get current team sheet
    response = t_tbl.get_item(Key={"teamId": match_id, "round": str(round_number)})
    item = response.get("Item")
    if not item:
        return {"error": f"No team sheet found for {match_id} round {round_number}"}

    home_team = item.get("homeTeam", "Unknown")
    away_team = item.get("awayTeam", "Unknown")
    home_spine = _extract_spine(item.get("homePlayers", []))
    away_spine = _extract_spine(item.get("awayPlayers", []))

    home_analysis = _analyse_team(home_team, home_spine, round_number, t_tbl, r_tbl)
    away_analysis = _analyse_team(away_team, away_spine, round_number, t_tbl, r_tbl)

    # Synergy edge summary
    home_games = home_analysis["full_spine_games_together"]
    away_games = away_analysis["full_spine_games_together"]
    if home_games > away_games + 3:
        edge = f"{home_team} have a significant spine synergy advantage ({home_games} games together vs {away_games})"
    elif away_games > home_games + 3:
        edge = f"{away_team} have a significant spine synergy advantage ({away_games} games together vs {home_games})"
    elif home_games > away_games:
        edge = f"{home_team} have a slight spine synergy edge ({home_games} vs {away_games} games together)"
    elif away_games > home_games:
        edge = f"{away_team} have a slight spine synergy edge ({away_games} vs {home_games} games together)"
    else:
        edge = f"Even spine synergy ({home_games} games together each)"

    return {
        "home_team": home_analysis,
        "away_team": away_analysis,
        "synergy_edge": edge,
    }
