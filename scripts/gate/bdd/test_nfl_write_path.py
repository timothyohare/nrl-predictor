"""Step definitions for nfl_write_path.feature — the NFL orchestrator write path
(spec Phase 3, criterion 3.10).

Runs in-process against DynamoDB Local, like test_write_path.py. Not collected by
plain pytest — scripts/gate/ is outside testpaths; the acceptance binding invokes
`python -m pytest scripts/gate/bdd` explicitly. CloudWatch is stubbed: the gate
must never call real AWS.
"""
import os
from datetime import UTC, datetime
from pathlib import Path

import boto3
import pytest
from pytest_bdd import given, parsers, scenarios, then, when

scenarios("nfl_write_path.feature")

FIXTURE_CSV = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "nfl_games_sample.csv"
NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
WEEK_8 = {
    "nfl-2026-week-8-packers-v-panthers",
    "nfl-2026-week-8-broncos-v-chiefs",
    "nfl-2026-week-8-jets-v-raiders",
    "nfl-2026-week-8-rams-v-chargers",
}
WEEKS_5_AND_7 = {
    "nfl-2026-week-5-commanders-v-giants",
    "nfl-2026-week-7-bears-v-patriots",
    "nfl-2026-week-7-saints-v-steelers",
    "nfl-2026-week-7-ravens-v-bengals",
}


def _ddb():
    return boto3.resource("dynamodb", region_name=os.environ.get("AWS_DEFAULT_REGION", "ap-southeast-2"))


def _table(env_var: str):
    return _ddb().Table(os.environ[env_var])


def _scan(table) -> list[dict]:
    items: list[dict] = []
    kwargs: dict = {}
    while True:
        resp = table.scan(**kwargs)
        items.extend(resp["Items"])
        if "LastEvaluatedKey" not in resp:
            return items
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


class _StubCloudWatch:
    def __init__(self, sink: list) -> None:
        self._sink = sink

    def put_metric_data(self, **kwargs) -> None:
        self._sink.append(kwargs)


@pytest.fixture
def ctx(monkeypatch) -> dict:
    from nfl.orchestrator import lambda_handler

    ctx: dict = {"metrics": []}
    real_client = lambda_handler.boto3.client

    def client(service, *args, **kwargs):
        if service == "cloudwatch":
            return _StubCloudWatch(ctx["metrics"])
        return real_client(service, *args, **kwargs)

    monkeypatch.setattr(lambda_handler.boto3, "client", client)
    return ctx


# --- given ---------------------------------------------------------------------

@given("empty NFL tables")
def empty_tables() -> None:
    for env_var, keys in (("NFL_GAMES_TABLE", ("matchId",)),
                          ("NFL_PREDICTIONS_TABLE", ("matchId", "generatedAt"))):
        table = _table(env_var)
        with table.batch_writer() as batch:
            for item in _scan(table):
                batch.delete_item(Key={k: item[k] for k in keys})


@given("the nflverse fixture CSV is the data source")
def fixture_source(monkeypatch) -> None:
    monkeypatch.setenv("NFL_GAMES_CSV_URL", FIXTURE_CSV.as_uri())


@given("the clock is frozen before the 2026 week 8 kickoffs")
def frozen_clock(monkeypatch) -> None:
    from nfl.orchestrator import lambda_handler

    monkeypatch.setattr(lambda_handler, "_now", lambda: NOW)


@given("the NFL orchestrator has run")
@when("the NFL orchestrator runs")
@when("the NFL orchestrator runs again")
def run_orchestrator(ctx: dict) -> None:
    from nfl.orchestrator.lambda_handler import lambda_handler

    ctx["summary"] = lambda_handler({}, None)


@when("the NFL backfill runs")
def run_backfill(ctx: dict) -> None:
    from common.nfl.games import parse_csv
    from nfl.orchestrator.backfill import backfill

    games, _ = parse_csv(FIXTURE_CSV.read_text())
    ctx["backfilled"] = backfill(games, _table("NFL_PREDICTIONS_TABLE"), NOW)


# --- then ----------------------------------------------------------------------

@then("nfl_predictions holds exactly the week-8 games")
def exactly_week_8() -> None:
    rows = _scan(_table("NFL_PREDICTIONS_TABLE"))
    assert sorted(r["matchId"] for r in rows) == sorted(WEEK_8)


@then(parsers.parse('every NFL prediction is an OK live row stamped "{model}" with scraped_at'))
def ok_live_rows(model: str) -> None:
    for row in _scan(_table("NFL_PREDICTIONS_TABLE")):
        assert row["status"] == "OK"
        assert row["backfilled"] is False
        assert row["model_used"] == model
        assert row["week"] == 8 and row["season"] == 2026
        assert row["scraped_at"]


@then("nfl_games holds the 2026 games, each with scraped_at")
def games_upserted() -> None:
    items = _scan(_table("NFL_GAMES_TABLE"))
    assert items
    assert all(i["season"] == 2026 for i in items)
    assert all(i["scraped_at"] for i in items)
    assert WEEK_8 | WEEKS_5_AND_7 <= {i["matchId"] for i in items}


@then(parsers.parse("it emits an UnpredictedGames metric of {n:d}"))
def emits_metric(ctx: dict, n: int) -> None:
    datum = ctx["metrics"][-1]
    assert datum["Namespace"] == "NflPredictor"
    assert datum["MetricData"][0]["MetricName"] == "UnpredictedGames"
    assert datum["MetricData"][0]["Value"] == n


@then("the 2026 weeks 5 and 7 games have backfilled rows")
def backfilled_rows(ctx: dict) -> None:
    assert set(ctx["backfilled"]) == WEEKS_5_AND_7
    rows = [r for r in _scan(_table("NFL_PREDICTIONS_TABLE")) if r["matchId"] in WEEKS_5_AND_7]
    assert len(rows) == len(WEEKS_5_AND_7)
    assert all(r["backfilled"] is True and r["status"] == "OK" for r in rows)


@then("the week-8 games still have only their live row")
def live_rows_untouched() -> None:
    rows = [r for r in _scan(_table("NFL_PREDICTIONS_TABLE")) if r["matchId"] in WEEK_8]
    assert sorted(r["matchId"] for r in rows) == sorted(WEEK_8)
    assert all(r["backfilled"] is False for r in rows)
