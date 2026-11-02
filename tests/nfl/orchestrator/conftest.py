"""Shared fixtures for the NFL orchestrator tests: moto tables, the fixture CSV
served over file://, CSV edits and a frozen clock."""
from __future__ import annotations

import csv
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import boto3
import pytest
from moto import mock_aws

FIXTURE_CSV = Path(__file__).resolve().parents[2] / "fixtures" / "nfl_games_sample.csv"
REGION = "ap-southeast-2"

WEEK_8 = {
    "nfl-2026-week-8-packers-v-panthers",
    "nfl-2026-week-8-broncos-v-chiefs",
    "nfl-2026-week-8-jets-v-raiders",
    "nfl-2026-week-8-rams-v-chargers",
}
# Tue 2026-10-27 22:00 AEDT: week 7 fully scored, before every week-8 kickoff.
BEFORE_WEEK_8 = "2026-10-28T12:00:00+00:00"


@pytest.fixture
def nfl_env(monkeypatch):
    monkeypatch.setenv("NFL_GAMES_TABLE", "nfl_games")
    monkeypatch.setenv("NFL_PREDICTIONS_TABLE", "nfl_predictions")
    monkeypatch.setenv("NFL_GAMES_CSV_URL", FIXTURE_CSV.as_uri())
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)


@pytest.fixture
def tables(nfl_env):
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


@pytest.fixture
def csv_with(tmp_path, monkeypatch) -> Callable[[Callable[[list[dict]], list[dict]]], Path]:
    """Write an edited copy of the fixture CSV and point NFL_GAMES_CSV_URL at it."""

    def _write(edit: Callable[[list[dict]], list[dict]]) -> Path:
        with FIXTURE_CSV.open(newline="") as fh:
            reader = csv.DictReader(fh)
            fieldnames = list(reader.fieldnames or [])
            rows = edit(list(reader))
        path = tmp_path / "games.csv"
        with path.open("w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        monkeypatch.setenv("NFL_GAMES_CSV_URL", path.as_uri())
        return path

    return _write


def unscore(game_id: str) -> Callable[[list[dict]], list[dict]]:
    def edit(rows: list[dict]) -> list[dict]:
        for row in rows:
            if row["game_id"] == game_id:
                row["home_score"] = row["away_score"] = row["result"] = ""
        return rows

    return edit


@pytest.fixture
def freeze(monkeypatch):
    """Freeze the handler's clock at an ISO instant."""
    from nfl.orchestrator import lambda_handler

    def _freeze(iso: str) -> datetime:
        now = datetime.fromisoformat(iso)
        monkeypatch.setattr(lambda_handler, "_now", lambda: now)
        return now

    return _freeze


def scan(table) -> list[dict]:
    items: list[dict] = []
    kwargs: dict = {}
    while True:
        resp = table.scan(**kwargs)
        items.extend(resp["Items"])
        if "LastEvaluatedKey" not in resp:
            return items
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
