import json
import os
from datetime import datetime, timezone

import boto3
import requests

from scrapers.shared.http_client import get_with_retry
from scrapers.shared.models import Match
from scrapers.shared.s3_cache import save_raw

_DRAW_URL = "https://www.nrl.com/draw/data?competition=111&season={season}&round={round}"


def fetch_draw(season: int, round_number: int) -> dict:
    _, body = get_with_retry(_DRAW_URL.format(season=season, round=round_number))
    return json.loads(body)


def parse_draw(data: dict) -> list[Match]:
    matches = []
    for fixture in data.get("fixtures", []):
        url = fixture.get("matchCentreUrl")
        if not url:
            continue
        # slug is the last path segment, e.g. "panthers-v-broncos"
        match_id = url.rstrip("/").rsplit("/", 1)[-1]
        kick_off = fixture.get("clock", {}).get("kickOffTimeLong") or None
        matches.append(Match(
            match_id=match_id,
            home_team=fixture["homeTeam"]["nickName"],
            away_team=fixture["awayTeam"]["nickName"],
            venue=fixture.get("venue", {}).get("name", ""),
            round_number=fixture.get("roundNumber", 0),
            kick_off=kick_off,
            match_state=fixture.get("matchState", ""),
        ))
    return matches


def lambda_handler(event: dict, context) -> None:
    season = event["season"]
    round_number = event["round"]
    table_name = os.environ["TEAMS_TABLE"]
    bucket = os.environ["RAW_BUCKET"]
    scraped_at = datetime.now(timezone.utc).isoformat()

    raw = fetch_draw(season, round_number)
    save_raw(bucket, f"raw-scrapes/draw/{season}/round-{round_number}.json", json.dumps(raw))

    matches = parse_draw(raw)
    table = boto3.resource("dynamodb").Table(table_name)

    with table.batch_writer() as batch:
        for match in matches:
            for side, team in (("home", match.home_team), ("away", match.away_team)):
                batch.put_item(Item={
                    "teamId": f"{match.match_id}#{side}",
                    "round": str(round_number),
                    "matchId": match.match_id,
                    "team": team,
                    "venue": match.venue,
                    "kickOff": match.kick_off or "",
                    "matchState": match.match_state,
                    "scraped_at": scraped_at,
                })
