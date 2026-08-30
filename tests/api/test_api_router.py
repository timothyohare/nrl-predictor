import json

import pytest
from moto import mock_aws

from v1.api.router import lambda_handler

SENTINEL = {"statusCode": 200, "headers": {}, "body": '{"dispatched":true}'}


@pytest.fixture
def no_rate_limit(monkeypatch):
    monkeypatch.delenv("RATE_LIMITS_TABLE", raising=False)


def test_health_returns_ok(no_rate_limit):
    response = lambda_handler({"rawPath": "/health"}, {})
    assert response["statusCode"] == 200
    assert json.loads(response["body"]) == {"status": "ok"}


def test_predictions_path_dispatches_to_predictions_handler(no_rate_limit, mocker):
    spy = mocker.patch("v1.api.predictions.lambda_handler", return_value=SENTINEL)
    event = {"rawPath": "/predictions/12"}
    assert lambda_handler(event, {}) is SENTINEL
    spy.assert_called_once_with(event, {})


def test_accuracy_path_dispatches_to_accuracy_handler(no_rate_limit, mocker):
    spy = mocker.patch("v1.api.accuracy.lambda_handler", return_value=SENTINEL)
    assert lambda_handler({"rawPath": "/accuracy"}, {}) is SENTINEL
    spy.assert_called_once()


def test_tournament_path_dispatches_to_tournament_handler(no_rate_limit, mocker):
    spy = mocker.patch("v1.api.tournament.lambda_handler", return_value=SENTINEL)
    assert lambda_handler({"rawPath": "/tournament/leaderboard"}, {}) is SENTINEL
    spy.assert_called_once()


def test_unknown_path_returns_404(no_rate_limit):
    response = lambda_handler({"rawPath": "/nope"}, {})
    assert response["statusCode"] == 404
    assert json.loads(response["body"]) == {"error": "Not found"}


def test_legacy_path_key_resolves_like_raw_path(no_rate_limit, mocker):
    spy = mocker.patch("v1.api.accuracy.lambda_handler", return_value=SENTINEL)
    assert lambda_handler({"path": "/accuracy"}, {}) is SENTINEL
    spy.assert_called_once()


def test_trailing_slash_is_stripped(no_rate_limit):
    response = lambda_handler({"rawPath": "/health/"}, {})
    assert response["statusCode"] == 200
    assert json.loads(response["body"]) == {"status": "ok"}


@mock_aws
def test_rate_limited_request_returns_429(monkeypatch, mocker):
    monkeypatch.setenv("RATE_LIMITS_TABLE", "nrl-rate-limits")
    mocker.patch(
        "v1.api.router.check_rate_limit",
        return_value=(False, "Rate limit exceeded: 20 requests/hour"),
    )
    response = lambda_handler({"rawPath": "/health"}, {})
    assert response["statusCode"] == 429
    assert response["headers"]["Retry-After"] == "3600"
    assert json.loads(response["body"]) == {"error": "Rate limit exceeded: 20 requests/hour"}


@mock_aws
def test_rate_limit_allowed_falls_through_to_dispatch(monkeypatch, mocker):
    monkeypatch.setenv("RATE_LIMITS_TABLE", "nrl-rate-limits")
    check = mocker.patch("v1.api.router.check_rate_limit", return_value=(True, "ok"))
    response = lambda_handler({"rawPath": "/health"}, {})
    assert response["statusCode"] == 200
    check.assert_called_once()


def test_rate_check_skipped_when_table_unset(no_rate_limit, mocker):
    check = mocker.patch("v1.api.router.check_rate_limit")
    response = lambda_handler({"rawPath": "/health"}, {})
    assert response["statusCode"] == 200
    check.assert_not_called()
