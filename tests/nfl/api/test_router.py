"""NFL API Lambda entry point (spec Phase 4): routing, health and rate limiting
(criterion 4.8 — reuses v1.api.rate_limit, fails open)."""
from __future__ import annotations

import boto3
import pytest

from nfl.api import router
from tests.nfl.api.conftest import REGION, body, event, game, prediction, put

GB = "nfl-2026-week-8-packers-v-panthers"


def call(path: str, **kwargs) -> dict:
    return router.lambda_handler(event(path, **kwargs), None)


def test_health(tables):
    response = call("/health")
    assert response["statusCode"] == 200
    assert response["headers"]["Content-Type"] == "application/json"
    assert body(response) == {"status": "ok"}


def test_routes_predictions_with_api_gateway_path_parameters(tables):
    put(tables.games, game(GB))
    put(tables.predictions, prediction(GB, winner="packers"))
    response = call("/nfl/predictions/2026/8", path_parameters={"season": "2026", "week": "8"})
    assert response["statusCode"] == 200
    assert [p["matchId"] for p in body(response)] == [GB]


def test_routes_predictions_from_the_path_when_parameters_are_absent(tables):
    put(tables.games, game(GB))
    put(tables.predictions, prediction(GB, winner="packers"))
    response = call("/nfl/predictions/2026/8/")
    assert response["statusCode"] == 200
    assert [p["matchId"] for p in body(response)] == [GB]


def test_bad_week_through_the_router_is_400(tables):
    assert call("/nfl/predictions/2026/eight")["statusCode"] == 400


def test_routes_weeks_current(tables):
    put(tables.games, game(GB, kickoff="2099-01-01T00:00:00Z"))
    response = call("/nfl/weeks/current")
    assert response["statusCode"] == 200
    assert body(response)["week"] == 8


def test_routes_weeks_list(tables):
    put(tables.games, game(GB))
    response = call("/nfl/weeks", query={"season": "2026"})
    assert response["statusCode"] == 200
    assert body(response)["weeks"] == [{"week": 8, "stage": "REG", "label": "Week 8"}]


def test_routes_accuracy(tables):
    put(tables.games, game(GB, score=(24, 17)))
    put(tables.predictions, prediction(GB, winner="packers"))
    response = call("/nfl/accuracy", query={"season": "2026"})
    assert response["statusCode"] == 200
    assert body(response)["n"] == 1


@pytest.mark.parametrize("path", [
    "/nfl", "/nfl/predictions", "/nfl/predictions/2026", "/nfl/predictions/2026/8/extra",
    "/predictions/12", "/accuracy", "/nope", "",
])
def test_unknown_path_is_404(tables, path):
    response = call(path)
    assert response["statusCode"] == 404
    assert "error" in body(response)


# --- 4.8 rate limiting -------------------------------------------------------------

def test_denied_request_is_429(tables, monkeypatch):
    monkeypatch.setenv("RATE_LIMITS_TABLE", "nrl-rate-limits")
    monkeypatch.setattr(router, "check_rate_limit",
                        lambda ip, table=None: (False, "Rate limit exceeded: 20 requests/hour"))
    response = call("/health")
    assert response["statusCode"] == 429
    assert response["headers"]["Retry-After"] == "3600"
    assert "Rate limit" in body(response)["error"]


def test_rate_limit_bucket_is_per_ip_and_separate_from_nrl(tables, monkeypatch):
    monkeypatch.setenv("RATE_LIMITS_TABLE", "nrl-rate-limits")
    seen = []
    monkeypatch.setattr(router, "check_rate_limit",
                        lambda ip, table=None: seen.append(ip) or (True, "ok"))
    call("/health", ip="198.51.100.9")
    assert seen == ["nfl#198.51.100.9"]


def test_rate_limit_counts_in_the_shared_table(tables, monkeypatch):
    monkeypatch.setenv("RATE_LIMITS_TABLE", "nrl-rate-limits")
    ddb = boto3.resource("dynamodb", region_name=REGION)
    limits = ddb.create_table(
        TableName="nrl-rate-limits",
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    statuses = [call("/health", ip="198.51.100.9")["statusCode"] for _ in range(21)]
    assert statuses == [200] * 20 + [429]
    (item,) = limits.scan()["Items"]
    assert item["pk"].startswith("nfl#198.51.100.9#hour#")


def test_fails_open_when_dynamodb_raises(tables, monkeypatch):
    monkeypatch.setenv("RATE_LIMITS_TABLE", "no-such-table")  # update_item raises
    assert call("/health")["statusCode"] == 200


def test_fails_open_when_the_rate_limiter_itself_raises(tables, monkeypatch):
    monkeypatch.setenv("RATE_LIMITS_TABLE", "nrl-rate-limits")

    def boom(ip, table=None):
        raise RuntimeError("dynamodb unreachable")

    monkeypatch.setattr(router, "check_rate_limit", boom)
    assert call("/health")["statusCode"] == 200


def test_no_rate_limit_table_configured_skips_the_check(tables, monkeypatch):
    calls = []
    monkeypatch.setattr(router, "check_rate_limit", lambda *a, **k: calls.append(a) or (False, "x"))
    assert call("/health")["statusCode"] == 200
    assert calls == []


def test_unexpected_error_is_a_clean_500_without_internals(tables, monkeypatch, caplog):
    def boom(event, context):
        raise RuntimeError("secret-internal-detail")

    monkeypatch.setattr(router.weeks, "lambda_handler", boom)
    with caplog.at_level("ERROR"):
        response = call("/nfl/weeks/current")
    assert response["statusCode"] == 500
    assert response["headers"]["Content-Type"] == "application/json"
    assert body(response) == {"error": "Internal error"}
    assert "secret-internal-detail" not in response["body"]
    assert "secret-internal-detail" in caplog.text
