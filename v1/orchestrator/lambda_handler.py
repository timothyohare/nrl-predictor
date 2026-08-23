import json
import logging
import os
from datetime import UTC, datetime

import boto3

from scrapers.nrl.draw import fetch_draw, parse_draw
from scrapers.nrl.team_sheet import (
    TeamSheetNotFound,
    fetch_team_sheet_page,
    parse_team_sheet,
)
from scrapers.shared.s3_cache import save_raw
from v1.orchestrator.stats_predictor import predict_round

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def lambda_handler(event: dict, context) -> dict:
    season = int(event.get("season", 2026))
    round_input = event.get("round")
    if round_input is None:
        raise ValueError("orchestrator event must include 'round' (int or 'current')")
    round_for_fetch = round_input if round_input == "current" else int(round_input)

    bucket = os.environ["RAW_BUCKET"]
    teams_table_name = os.environ["TEAMS_TABLE"]
    scraped_at = datetime.now(UTC).isoformat()

    # 1. Scrape draw
    raw_draw = fetch_draw(season, round_for_fetch)
    matches = parse_draw(raw_draw)
    if not matches:
        logger.warning("No matches parsed for season=%s round=%s", season, round_input)
        return {"matches": 0, "predicted": []}

    actual_round = matches[0].round_number
    save_raw(bucket, f"raw-scrapes/draw/{season}/round-{actual_round}.json", json.dumps(raw_draw))
    logger.info("Parsed %d matches for round %s", len(matches), actual_round)

    # 2. Write draw entries to teams table
    teams_table = boto3.resource("dynamodb").Table(teams_table_name)
    with teams_table.batch_writer() as batch:
        for match in matches:
            for side, team in (("home", match.home_team), ("away", match.away_team)):
                batch.put_item(Item={
                    "teamId": f"{match.match_id}#{side}",
                    "round": str(match.round_number),
                    "matchId": match.match_id,
                    "team": team,
                    "venue": match.venue,
                    "kickOff": match.kick_off or "",
                    "matchState": match.match_state,
                    "matchCentreUrl": match.match_centre_url,
                    "scraped_at": scraped_at,
                })

    # 3. Scrape team sheets inline (best-effort — prediction runs regardless;
    # the stats model doesn't currently read team sheets, but scraping stays
    # here since other consumers — API display, future signals — rely on it)
    for match in matches:
        if not match.match_centre_url:
            continue
        try:
            q_data = fetch_team_sheet_page(match.match_centre_url)
            save_raw(
                bucket,
                f"raw-scrapes/team-sheet/{match.match_centre_url.strip('/')}.json",
                json.dumps(q_data),
            )
            ts = parse_team_sheet(q_data)
            ts.scraped_at = scraped_at
            teams_table.put_item(Item={
                # Key by the slug the agent is invoked with / queries by, not the
                # numerical NRL matchId from the q-data.
                "teamId": match.match_id,
                "round": str(match.round_number),
                "matchState": ts.match_state,
                "kickOff": ts.kick_off or "",
                "homeTeam": ts.home_team.nick_name,
                "awayTeam": ts.away_team.nick_name,
                "homePlayers": [p.__dict__ for p in ts.home_team.players],
                "awayPlayers": [p.__dict__ for p in ts.away_team.players],
                "homeScore": ts.home_team.score,
                "awayScore": ts.away_team.score,
                "scraped_at": scraped_at,
            })
        except TeamSheetNotFound as e:
            logger.warning("Team sheet not available for %s: %s", match.match_id, e)
        except Exception as e:
            logger.error("Team sheet scrape failed for %s: %s", match.match_id, e, exc_info=True)

    # 4. Predict every match locally via the Elo + Monte Carlo model — no
    # external API call, no rate limit, no Anthropic credit dependency. See
    # docs/plans/10-elo-monte-carlo-predictor.md, Phase 3 cutover.
    predictions_table = boto3.resource("dynamodb").Table(os.environ["PREDICTIONS_TABLE"])
    results_table = boto3.resource("dynamodb").Table(os.environ["RESULTS_TABLE"])
    predicted = predict_round(
        matches, round_number=actual_round, season=season,
        predictions_table=predictions_table, results_table=results_table,
    )

    logger.info("Predicted %d/%d matches", len(predicted), len(matches))
    return {
        "round": actual_round,
        "matches": len(matches),
        "predicted": predicted,
    }
