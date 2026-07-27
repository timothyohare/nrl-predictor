"""Gather the same deterministic data the prediction agent's tools fetch —
team sheets, injuries, recent form, head-to-head, weather, ladder, fantasy
signals, venue profile, lessons, coaching matchup, trap game, spine synergy —
for every match in a round, WITHOUT calling the Anthropic API.

Every one of these tools is a plain DynamoDB read (or, for fantasy_stats/
venue_profile, a live HTTP call / static lookup) — the only part of the
agent's run that actually needs Claude is the reasoning + JSON prediction
step. This script does the free part and writes:

  - a `match_context` DynamoDB row per match (audit trail / reusable data), and
  - a paste-ready prompt file per match (system prompt + gathered data folded
    into the user message) so the reasoning step can be done for free in a
    Claude Pro chat session instead of the metered API.

Usage:
    # Preview only — no DynamoDB writes, no prompt files
    AWS_DEFAULT_REGION=ap-southeast-2 python3 scripts/gather_round_context.py --round 11 --season 2026 --dry-run

    # Gather for real
    AWS_DEFAULT_REGION=ap-southeast-2 python3 scripts/gather_round_context.py --round 11 --season 2026

Companion script `scripts/ingest_manual_prediction.py` closes the loop by
writing Claude's pasted JSON response back into the real `predictions` table.
"""
import argparse
import json
import os
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import boto3

from scrapers.nrl.draw import fetch_draw, parse_draw
from scrapers.shared.models import Match
from v1.agent.prompt import PROMPT_VERSION, build_system_prompt
from v1.agent.tools.coaching_matchup import get_coaching_matchup
from v1.agent.tools.fantasy_stats import get_fantasy_stats
from v1.agent.tools.head_to_head import get_head_to_head
from v1.agent.tools.injury_list import get_injury_list
from v1.agent.tools.ladder import get_ladder
from v1.agent.tools.lessons import get_lessons
from v1.agent.tools.recent_form import get_recent_form
from v1.agent.tools.spine_synergy import get_spine_synergy
from v1.agent.tools.team_sheet import get_team_sheet
from v1.agent.tools.trap_game import detect_trap_game
from v1.agent.tools.venue_profile import get_venue_profile
from v1.agent.tools.weather import get_weather

REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "ap-southeast-2"


def _safe_call(fn, *args, **kwargs) -> Any:
    """Call a tool function; on any failure, isolate it to a single key
    rather than aborting the whole match's gathering run."""
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        return {"error": str(e)}


def fetch_round_matches(season: int, round_number: int) -> list[Match]:
    """The same draw fetch the orchestrator uses — no new scraper needed."""
    return parse_draw(fetch_draw(season, round_number))


def gather_match_data(
    match: Match,
    season: int,
    *,
    teams_table=None,
    results_table=None,
    injuries_table=None,
    weather_table=None,
    retro_table=None,
) -> dict[str, Any]:
    """Call every tool the agent would call for this match, deterministically
    and with no LLM involved. Each tool's failure is isolated to its own key."""
    home, away = match.home_team, match.away_team

    data: dict[str, Any] = {
        "team_sheet": _safe_call(
            get_team_sheet, match.match_id, match.round_number, table=teams_table
        ),
        "injuries": {
            "home": _safe_call(get_injury_list, home, table=injuries_table),
            "away": _safe_call(get_injury_list, away, table=injuries_table),
        },
        "recent_form": {
            "home": _safe_call(get_recent_form, home, table=results_table, exclude_match_id=match.match_id),
            "away": _safe_call(get_recent_form, away, table=results_table, exclude_match_id=match.match_id),
        },
        "head_to_head": _safe_call(
            get_head_to_head, home, away, venue=match.venue, table=results_table
        ),
        "ladder": _safe_call(get_ladder, season, table=teams_table),
        "fantasy_stats": {
            "home": _safe_call(get_fantasy_stats, home),
            "away": _safe_call(get_fantasy_stats, away),
        },
        "venue_profile": _safe_call(get_venue_profile, match.venue),
        "lessons": _safe_call(get_lessons, season, limit=10, table=retro_table),
        "coaching_matchup": _safe_call(get_coaching_matchup, home, away, table=results_table),
        "trap_game": _safe_call(
            detect_trap_game,
            match.match_id, match.round_number, season, home, away,
            teams_table=teams_table, results_table=results_table,
        ),
        "spine_synergy": _safe_call(
            get_spine_synergy,
            match.match_id, match.round_number,
            teams_table=teams_table, results_table=results_table,
        ),
    }

    date = match.kick_off[:10] if match.kick_off else None
    if date is not None:
        data["weather"] = _safe_call(get_weather, match.venue, date, table=weather_table)
    else:
        data["weather"] = {"error": "no kickoff time available for this match"}

    return data


def build_context_row(match: Match, season: int, data: dict[str, Any], generated_at: str) -> dict[str, Any]:
    return {
        "matchId": match.match_id,
        "generatedAt": generated_at,
        "scraped_at": generated_at,
        "season": season,
        "roundNumber": match.round_number,
        "homeTeam": match.home_team,
        "awayTeam": match.away_team,
        "venue": match.venue,
        "kickOff": match.kick_off,
        "promptVersion": PROMPT_VERSION,
        "data": data,
    }


def render_prompt(row: dict[str, Any]) -> str:
    """Combine the agent's system prompt with the gathered data into a single
    paste-ready document — no tool-calling loop needed since all the data the
    tools would have fetched is already embedded in the user message."""
    lessons = row["data"].get("lessons")
    if not isinstance(lessons, list):
        lessons = None
    system_prompt = build_system_prompt(lessons=lessons)

    user_message = (
        "Analyse this match and produce a prediction.\n\n"
        f"match_id: {row['matchId']}\n\n"
        "All the data you need has already been gathered below — do not ask for more data "
        "or describe further tool calls. Output only the final JSON prediction object.\n\n"
        f"data: {json.dumps(row['data'], default=str, indent=2)}"
    )

    return (
        "=== SYSTEM PROMPT (paste as Project custom instructions, or prepend to your message) ===\n\n"
        f"{system_prompt}\n\n"
        "=== USER MESSAGE (paste this as your message) ===\n\n"
        f"{user_message}\n"
    )


def write_prompt_file(output_dir: Path, row: dict[str, Any], prompt_text: str) -> Path:
    round_dir = output_dir / str(row["season"]) / f"round-{row['roundNumber']}"
    round_dir.mkdir(parents=True, exist_ok=True)
    path = round_dir / f"{row['matchId']}.md"
    path.write_text(prompt_text)
    return path


def _dynamo_safe(obj: Any) -> Any:
    """Recursively convert floats to Decimal (e.g. momentum's weighted win
    rate) so boto3's DynamoDB resource will accept the item."""
    return json.loads(json.dumps(obj, default=str), parse_float=Decimal)


def gather_round(
    matches: list[Match],
    season: int,
    *,
    teams_table=None,
    results_table=None,
    injuries_table=None,
    weather_table=None,
    retro_table=None,
    context_table=None,
    output_dir: Path | None = None,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """Gather context for every match; write the match_context row and
    prompt file per match unless dry_run. Always returns the gathered rows."""
    rows = []
    for match in matches:
        data = gather_match_data(
            match, season,
            teams_table=teams_table, results_table=results_table,
            injuries_table=injuries_table, weather_table=weather_table,
            retro_table=retro_table,
        )
        generated_at = datetime.now(UTC).isoformat()
        row = build_context_row(match, season, data, generated_at)
        rows.append(row)

        if dry_run:
            continue
        if context_table is not None:
            try:
                context_table.put_item(Item=_dynamo_safe(row))
            except Exception as e:
                # Don't let a missing/unreachable match_context table block
                # the prompt file — that's the part actually needed to hand
                # a prediction to Claude.
                print(f"  [warn] could not write match_context row for {match.match_id}: {e}")
        if output_dir is not None:
            write_prompt_file(output_dir, row, render_prompt(row))

    return rows


def _count_errors(value: Any) -> int:
    if isinstance(value, dict):
        if set(value.keys()) == {"error"}:
            return 1
        return sum(_count_errors(v) for v in value.values())
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--round", type=int, required=True, help="Round number to gather")
    parser.add_argument("--season", type=int, default=datetime.now(UTC).year)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Gather and print a summary only; skip DynamoDB writes and prompt files",
    )
    parser.add_argument(
        "--output-dir", default="manual_context",
        help="Directory for paste-ready prompt files (default: manual_context/)",
    )
    args = parser.parse_args()

    ddb = boto3.resource("dynamodb", region_name=REGION)
    teams_table = ddb.Table(os.environ.get("TEAMS_TABLE", "teams"))
    results_table = ddb.Table(os.environ.get("RESULTS_TABLE", "results"))
    injuries_table = ddb.Table(os.environ.get("INJURIES_TABLE", "injuries"))
    weather_table = ddb.Table(os.environ.get("WEATHER_TABLE", "weather"))
    retro_table = ddb.Table(os.environ.get("RETROSPECTIVES_TABLE", "retrospectives"))
    context_table = None if args.dry_run else ddb.Table(os.environ.get("MATCH_CONTEXT_TABLE", "match_context"))

    matches = fetch_round_matches(args.season, args.round)
    print(f"Round {args.round}, season {args.season}: {len(matches)} matches\n")

    rows = gather_round(
        matches, args.season,
        teams_table=teams_table, results_table=results_table,
        injuries_table=injuries_table, weather_table=weather_table,
        retro_table=retro_table,
        context_table=context_table,
        output_dir=None if args.dry_run else Path(args.output_dir),
        dry_run=args.dry_run,
    )

    for row in rows:
        errors = _count_errors(row["data"])
        status = f"{errors} tool error(s)" if errors else "OK"
        print(f"  {row['matchId']}: {status}")

    if args.dry_run:
        print("\nDRY RUN — no DynamoDB writes or prompt files. Re-run without --dry-run to write.")
    else:
        print(f"\nWrote {len(rows)} match_context row(s) and prompt file(s) under {args.output_dir}/")


if __name__ == "__main__":
    main()
