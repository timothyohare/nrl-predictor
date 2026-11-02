"""Shared fixtures for the NFL API tests (spec Phase 4): moto tables, seeded
nfl_games / nfl_predictions rows and an HTTP API v2 event builder."""
from __future__ import annotations

import json
from decimal import Decimal
from types import SimpleNamespace

import boto3
import pytest
from moto import mock_aws

REGION = "ap-southeast-2"


@pytest.fixture
def api_env(monkeypatch):
    monkeypatch.setenv("NFL_GAMES_TABLE", "nfl_games")
    monkeypatch.setenv("NFL_PREDICTIONS_TABLE", "nfl_predictions")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    monkeypatch.delenv("RATE_LIMITS_TABLE", raising=False)


@pytest.fixture
def tables(api_env):
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name=REGION)
        games = ddb.create_table(
            TableName="nfl_games",
            KeySchema=[{"AttributeName": "matchId", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "matchId", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        predictions = ddb.create_table(
            TableName="nfl_predictions",
            KeySchema=[
                {"AttributeName": "matchId", "KeyType": "HASH"},
                {"AttributeName": "generatedAt", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "matchId", "AttributeType": "S"},
                {"AttributeName": "generatedAt", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        yield SimpleNamespace(games=games, predictions=predictions)


def game(match_id: str, *, stage: str = "REG", kickoff: str = "2026-11-01T18:00:00Z",
         neutral: bool = False, score: tuple[int, int] | None = None,
         market: dict | None = None) -> dict:
    """An nfl_games item in the shape the orchestrator writes (game_item)."""
    _, season, _, week, *_ = match_id.split("-", 4)
    home, away = match_id.split(f"week-{week}-", 1)[1].split("-v-")
    item: dict = {
        "matchId": match_id, "game_id": f"{season}_{int(week):02d}_X_Y",
        "season": int(season), "week": int(week), "stage": stage,
        "home_team": home, "away_team": away, "neutral": neutral,
        "played": score is not None, "kickoff_utc": kickoff,
        "scraped_at": "2026-10-28T12:00:00+00:00",
    }
    if score is not None:
        item["home_score"], item["away_score"] = score
    if market is not None:
        item["market"] = {k: Decimal(str(v)) if isinstance(v, float) else v
                          for k, v in market.items()}
    return item


def prediction(match_id: str, *, winner: str, margin: int = 4, generated_at: str = "2026-10-28T12:00:00+00:00",
               status: str = "OK", p_home: str = "0.6", confidence: str = "MEDIUM",
               backfilled: bool = False, generation: int = 1) -> dict:
    """An nfl_predictions row in the shape store_prediction writes."""
    _, season, _, week, *_ = match_id.split("-", 4)
    row: dict = {
        "matchId": match_id, "generatedAt": generated_at, "season": int(season),
        "week": int(week), "model_used": "nfl-elo-v1", "generation": generation,
        "backfilled": backfilled, "scraped_at": generated_at, "status": status,
    }
    if status == "OK":
        row.update({
            "stage": "REG", "predicted_winner": winner, "predicted_margin": margin,
            "margin_low": max(margin - 6, 0), "margin_high": margin + 6,
            "home_win_probability": Decimal(p_home), "confidence": confidence,
            "key_factors": ["Elo rating gap"], "reasoning": "Elo.", "neutral": False,
            "kickoff_utc": "2026-11-01T18:00:00Z",
        })
    else:
        row["error"] = "boom"
    return row


def put(table, *items: dict) -> None:
    for item in items:
        table.put_item(Item=item)


def event(path: str, *, path_parameters: dict | None = None, query: dict | None = None,
          ip: str = "203.0.113.7") -> dict:
    return {
        "rawPath": path,
        "pathParameters": path_parameters,
        "queryStringParameters": query,
        "requestContext": {"http": {"method": "GET", "sourceIp": ip}},
    }


def body(response: dict):
    return json.loads(response["body"])
