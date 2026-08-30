"""Step definitions for write_path.feature — the async prediction/scoring path.

Runs in-process (no HTTP server, unlike the read-path feature) against DynamoDB
Local. Not collected by plain pytest — scripts/gate/ is outside testpaths; the
acceptance binding invokes `python -m pytest scripts/gate/bdd` explicitly.
"""
import os
from datetime import UTC, datetime

import boto3
import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from scrapers.shared.models import Match

scenarios("write_path.feature")

_CLUBS = ["panthers", "broncos", "storm", "eels", "roosters", "rabbitohs"]


def make_matches(round_number: int, n: int = 3) -> list[Match]:
    """Mirror of write_path_setup.seed_draw_kickoffs()'s club rotation."""
    out = []
    for i in range(n):
        home, away = _CLUBS[(2 * i) % 6], _CLUBS[(2 * i + 1) % 6]
        out.append(Match(
            match_id=f"round-{round_number}-{home}-v-{away}",
            home_team=home,
            away_team=away,
            venue="Test Stadium",
            round_number=round_number,
            kick_off=(datetime.now(UTC).replace(microsecond=0)).isoformat(),
            match_state="Upcoming",
        ))
    return out


def _ddb():
    return boto3.resource("dynamodb", region_name=os.environ.get("AWS_DEFAULT_REGION", "ap-southeast-2"))


def _predictions_table():
    return _ddb().Table(os.environ["PREDICTIONS_TABLE"])


def _rows_for(match_id: str) -> list[dict]:
    resp = _predictions_table().query(
        KeyConditionExpression="matchId = :m",
        ExpressionAttributeValues={":m": match_id},
    )
    return sorted(resp["Items"], key=lambda r: r["generatedAt"])


@pytest.fixture
def ctx() -> dict:
    return {}


# --- given ---------------------------------------------------------------------

@given(parsers.parse("a drawn round {round_number:d} of {n:d} matches"))
def drawn_round(ctx: dict, round_number: int, n: int) -> None:
    ctx["round"] = round_number
    ctx["matches"] = make_matches(round_number, n)


@given("the model raises for the first match")
def model_raises_first(ctx: dict, monkeypatch) -> None:
    from v1.orchestrator import stats_predictor

    target = ctx["matches"][0].match_id
    real = stats_predictor.predict_match

    def flaky(home, away, *a, **kw):
        # predict_match is called positionally with slugs; identify the target by
        # the round's first fixture pairing.
        first = ctx["matches"][0]
        if (home, away) == (first.home_team, first.away_team):
            raise RuntimeError(f"forced model failure for {target}")
        return real(home, away, *a, **kw)

    monkeypatch.setattr(stats_predictor, "predict_match", flaky)


@given(parsers.parse("only {k:d} of the {total:d} matches are predicted"))
def predict_subset(ctx: dict, k: int, total: int) -> None:
    from v1.orchestrator.stats_predictor import predict_round

    subset = ctx["matches"][:k]
    ctx["missing_match"] = ctx["matches"][k].match_id
    predict_round(
        subset, round_number=ctx["round"], season=2026,
        predictions_table=_predictions_table(), results_table=_ddb().Table(os.environ["RESULTS_TABLE"]),
    )


@given("the round is predicted")
def round_predicted(ctx: dict) -> None:
    from v1.orchestrator.stats_predictor import predict_round

    predict_round(
        ctx["matches"], round_number=ctx["round"], season=2026,
        predictions_table=_predictions_table(), results_table=_ddb().Table(os.environ["RESULTS_TABLE"]),
    )


@given("a full-time result exists for the first match")
def seed_result(ctx: dict) -> None:
    match = ctx["matches"][0]
    _ddb().Table(os.environ["RESULTS_TABLE"]).put_item(Item={
        "matchId": match.match_id,
        "scoredAt": "2026-08-01T10:00:00Z",
        "roundNumber": ctx["round"],
        "homeTeam": match.home_team,
        "awayTeam": match.away_team,
        "homeScore": 26,
        "awayScore": 12,
        "winner": match.home_team,
        "margin": 14,
        "matchState": "FullTime",
    })


# --- when ---------------------------------------------------------------------

@when("the stats predictor runs for the round")
@when("the stats predictor runs for the round again")
def run_predictor(ctx: dict) -> None:
    from v1.orchestrator.stats_predictor import predict_round

    predict_round(
        ctx["matches"], round_number=ctx["round"], season=2026,
        predictions_table=_predictions_table(), results_table=_ddb().Table(os.environ["RESULTS_TABLE"]),
    )


@when("the coverage check runs for the round")
def run_coverage_check(ctx: dict, monkeypatch) -> None:
    from v1.orchestrator import coverage_check

    monkeypatch.setattr(coverage_check, "fetch_draw", lambda season, rnd: {})
    monkeypatch.setattr(coverage_check, "parse_draw", lambda raw: ctx["matches"])

    emitted: list[dict] = []

    class _FakeCloudWatch:
        def put_metric_data(self, **kwargs):
            emitted.append(kwargs)

    real_client = coverage_check.boto3.client

    def client(service, *a, **kw):
        if service == "cloudwatch":
            return _FakeCloudWatch()
        return real_client(service, *a, **kw)

    monkeypatch.setattr(coverage_check.boto3, "client", client)
    ctx["cw_calls"] = emitted
    ctx["coverage_result"] = coverage_check.lambda_handler(
        {"season": 2026, "round": ctx["round"]}, None
    )


@when("the scoring lambda runs for the first match")
def run_scoring(ctx: dict, monkeypatch) -> None:
    from scoring import lambda_handler as scoring_handler

    monkeypatch.setenv("RETROSPECTIVE_FUNCTION_ARN", "arn:aws:lambda:ap-southeast-2:0:function:retro")

    invokes: list[dict] = []

    class _FakeLambda:
        def invoke(self, **kwargs):
            invokes.append(kwargs)
            return {"StatusCode": 202}

    real_client = scoring_handler.boto3.client

    def client(service, *a, **kw):
        if service == "lambda":
            return _FakeLambda()
        return real_client(service, *a, **kw)

    monkeypatch.setattr(scoring_handler.boto3, "client", client)
    ctx["lambda_invokes"] = invokes
    ctx["scoring_result"] = scoring_handler.lambda_handler(
        {"matchId": ctx["matches"][0].match_id, "round": ctx["round"], "season": 2026}, None
    )


# --- then -------------------------------------------------------------------

@then("every match has an OK prediction row")
def every_match_ok(ctx: dict) -> None:
    for m in ctx["matches"]:
        rows = _rows_for(m.match_id)
        assert any(r.get("status") == "OK" for r in rows), f"{m.match_id}: {rows}"


@then(parsers.parse('every prediction is stamped prompt_version "{version}"'))
def stamped_version(ctx: dict, version: str) -> None:
    for m in ctx["matches"]:
        ok = [r for r in _rows_for(m.match_id) if r.get("status") == "OK"]
        assert ok and all(r["prompt_version"] == version for r in ok)


@then("every prediction is generation 1")
def generation_one(ctx: dict) -> None:
    for m in ctx["matches"]:
        ok = [r for r in _rows_for(m.match_id) if r.get("status") == "OK"]
        assert ok and all(int(r["generation"]) == 1 for r in ok)


@then(parsers.parse("every match has {count:d} prediction rows"))
def n_rows(ctx: dict, count: int) -> None:
    for m in ctx["matches"]:
        rows = _rows_for(m.match_id)
        assert len(rows) == count, f"{m.match_id}: {len(rows)} rows"


@then(parsers.parse("the newest prediction per match is generation {gen:d}"))
def newest_generation(ctx: dict, gen: int) -> None:
    for m in ctx["matches"]:
        rows = _rows_for(m.match_id)
        assert int(rows[-1]["generation"]) == gen, rows


@then("the first match has a FAILED prediction row")
def first_failed(ctx: dict) -> None:
    rows = _rows_for(ctx["matches"][0].match_id)
    assert any(r.get("status") == "FAILED" and r.get("error") for r in rows), rows


@then(parsers.parse("the other {count:d} matches have an OK prediction row"))
def others_ok(ctx: dict, count: int) -> None:
    for m in ctx["matches"][1:]:
        rows = _rows_for(m.match_id)
        assert any(r.get("status") == "OK" for r in rows), f"{m.match_id}: {rows}"


@then(parsers.parse("it reports {n:d} missing match"))
def reports_missing(ctx: dict, n: int) -> None:
    result = ctx["coverage_result"]
    assert result["missing"] == [ctx["missing_match"]], result
    assert len(result["missing"]) == n


@then(parsers.parse("it emits a MissingPredictions metric of {value:d}"))
def emits_metric(ctx: dict, value: int) -> None:
    calls = ctx["cw_calls"]
    assert len(calls) == 1, calls
    data = calls[0]["MetricData"][0]
    assert data["MetricName"] == "MissingPredictions"
    assert data["Value"] == value


@then("the scoring lambda returns OK")
def scoring_ok(ctx: dict) -> None:
    assert ctx["scoring_result"]["status"] == "OK", ctx["scoring_result"]


@then("a scored result row carries the round number and a brier component")
def scored_row(ctx: dict) -> None:
    match_id = ctx["matches"][0].match_id
    resp = _ddb().Table(os.environ["RESULTS_TABLE"]).query(
        KeyConditionExpression="matchId = :m",
        ExpressionAttributeValues={":m": match_id},
    )
    scored = [r for r in resp["Items"] if "brier_component" in r]
    assert scored, resp["Items"]
    assert all(int(r["roundNumber"]) == ctx["round"] for r in scored)


@then("the round and season metric aggregates are written")
def metrics_written(ctx: dict) -> None:
    items = _ddb().Table(os.environ["METRICS_TABLE"]).scan()["Items"]
    periods = {i["period"] for i in items}
    assert f"2026-round-{ctx['round']}" in periods, periods
    assert "2026-season" in periods, periods


@then("the retrospective lambda was invoked once for the first match")
def retro_invoked(ctx: dict) -> None:
    invokes = ctx["lambda_invokes"]
    assert len(invokes) == 1, invokes
    call = invokes[0]
    assert call["InvocationType"] == "Event"
    assert ctx["matches"][0].match_id in call["Payload"]
