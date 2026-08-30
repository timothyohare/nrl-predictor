import json
from unittest.mock import ANY, patch

import boto3
import pytest
from moto import mock_aws

PRED_TABLE = "predictions"
RESULTS_TABLE = "results"
METRICS_TABLE = "metrics"
MATCH_ID = "panthers-v-broncos-20260515"


@pytest.fixture
def aws_env(monkeypatch):
    monkeypatch.setenv("PREDICTIONS_TABLE", PRED_TABLE)
    monkeypatch.setenv("RESULTS_TABLE", RESULTS_TABLE)
    monkeypatch.setenv("METRICS_TABLE", METRICS_TABLE)


@pytest.fixture
def tables():
    with mock_aws():
        client = boto3.client("dynamodb", region_name="ap-southeast-2")
        for name, pk, sk in [
            (PRED_TABLE, "matchId", "generatedAt"),
            (RESULTS_TABLE, "matchId", "scoredAt"),
            (METRICS_TABLE, "period", "metricName"),
        ]:
            client.create_table(
                TableName=name,
                KeySchema=[
                    {"AttributeName": pk, "KeyType": "HASH"},
                    {"AttributeName": sk, "KeyType": "RANGE"},
                ],
                AttributeDefinitions=[
                    {"AttributeName": pk, "AttributeType": "S"},
                    {"AttributeName": sk, "AttributeType": "S"},
                ],
                BillingMode="PAY_PER_REQUEST",
            )
        ddb = boto3.resource("dynamodb", region_name="ap-southeast-2")
        pred = ddb.Table(PRED_TABLE)
        results = ddb.Table(RESULTS_TABLE)
        pred.put_item(Item={
            "matchId": MATCH_ID,
            "generatedAt": "2026-05-15T20:00:00Z",
            "predicted_winner": "Panthers",
            "predicted_margin": 10,
            "confidence": "HIGH",
            "status": "OK",
            "roundNumber": 12,
            "season": 2026,
        })
        results.put_item(Item={
            "matchId": MATCH_ID,
            "scoredAt": "2026-05-16T11:30:00Z",
            "homeTeam": "Panthers",
            "awayTeam": "Broncos",
            "homeScore": 24,
            "awayScore": 18,
            "winner": "Panthers",
            "margin": 6,
            "matchState": "FullTime",
        })
        yield ddb


def test_scorer_lambda_writes_scored_result(aws_env, tables):
    from scoring.lambda_handler import lambda_handler
    with patch("scoring.lambda_handler.aggregate_round"):
        lambda_handler({"matchId": MATCH_ID, "round": 12, "season": 2026}, {})
    results_tbl = tables.Table(RESULTS_TABLE)
    items = results_tbl.scan()["Items"]
    scored = [i for i in items if "correct_pick" in i]
    assert len(scored) == 1
    assert scored[0]["correct_pick"] is True


def test_scorer_lambda_invokes_metrics_aggregation(aws_env, tables):
    from scoring.lambda_handler import lambda_handler
    with patch("scoring.lambda_handler.aggregate_round") as mock_agg:
        lambda_handler({"matchId": MATCH_ID, "round": 12, "season": 2026}, {})
    mock_agg.assert_called_once()


def test_results_row_carries_is_hindsight_false_for_honest_score(aws_env, tables):
    from scoring.lambda_handler import lambda_handler
    with patch("scoring.lambda_handler.aggregate_round"):
        lambda_handler({"matchId": MATCH_ID, "round": 12, "season": 2026}, {})
    results_tbl = tables.Table(RESULTS_TABLE)
    scored = [i for i in results_tbl.scan()["Items"] if "correct_pick" in i]
    assert scored[0]["is_hindsight"] is False


def test_hindsight_score_is_flagged_and_logged(aws_env, tables, monkeypatch, caplog):
    """Every existing OK prediction postdates kickoff (the leak scenario) -> score_prediction
    has no honest pre-kickoff pick to fall back on, and the result must say so, not silently
    look like a normal forecast."""
    from scoring.lambda_handler import lambda_handler

    monkeypatch.setenv("TEAMS_TABLE", "teams")
    teams_tbl = tables.create_table(
        TableName="teams",
        KeySchema=[{"AttributeName": "teamId", "KeyType": "HASH"},
                   {"AttributeName": "round", "KeyType": "RANGE"}],
        AttributeDefinitions=[{"AttributeName": "teamId", "AttributeType": "S"},
                              {"AttributeName": "round", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    # Kickoff predates the base fixture's only prediction (2026-05-15T20:00:00Z) — no
    # pre-kickoff candidate exists, forcing the hindsight fallback.
    teams_tbl.put_item(Item={"teamId": f"{MATCH_ID}#home", "round": "12", "kickOff": "2026-05-14T00:00:00Z"})

    with patch("scoring.lambda_handler.aggregate_round"), caplog.at_level("WARNING"):
        lambda_handler({"matchId": MATCH_ID, "round": 12, "season": 2026}, {})

    results_tbl = tables.Table(RESULTS_TABLE)
    scored = [i for i in results_tbl.scan()["Items"] if "correct_pick" in i]
    assert scored[0]["is_hindsight"] is True
    assert any("hindsight" in r.message.lower() for r in caplog.records)


# --- retrospective async trigger ---------------------------------------------------


def test_retrospective_triggered_on_successful_scoring(aws_env, tables, monkeypatch):
    monkeypatch.setenv(
        "RETROSPECTIVE_FUNCTION_ARN",
        "arn:aws:lambda:ap-southeast-2:000000000000:function:retro",
    )
    from scoring.lambda_handler import lambda_handler

    with patch("scoring.lambda_handler.aggregate_round"), \
         patch("scoring.lambda_handler.boto3.client") as mock_client:
        resp = lambda_handler({"matchId": MATCH_ID, "round": 12, "season": 2026}, {})

    assert resp == {"status": "OK", "matchId": MATCH_ID}
    mock_client.assert_called_once_with("lambda")
    invoke = mock_client.return_value.invoke
    invoke.assert_called_once()
    kwargs = invoke.call_args.kwargs
    assert kwargs["InvocationType"] == "Event"
    assert json.loads(kwargs["Payload"]) == {
        "matchId": MATCH_ID, "round": 12, "season": 2026,
    }


def test_retrospective_invoke_failure_is_swallowed(aws_env, tables, monkeypatch, caplog):
    monkeypatch.setenv(
        "RETROSPECTIVE_FUNCTION_ARN",
        "arn:aws:lambda:ap-southeast-2:000000000000:function:retro",
    )
    from scoring.lambda_handler import lambda_handler

    with patch("scoring.lambda_handler.aggregate_round"), \
         patch("scoring.lambda_handler.boto3.client") as mock_client, \
         caplog.at_level("WARNING"):
        mock_client.return_value.invoke.side_effect = RuntimeError("throttled")
        resp = lambda_handler({"matchId": MATCH_ID, "round": 12, "season": 2026}, {})

    # scoring still succeeds even though the retrospective trigger blew up
    assert resp == {"status": "OK", "matchId": MATCH_ID}
    assert "Failed to trigger retrospective" in caplog.text
    scored = [i for i in tables.Table(RESULTS_TABLE).scan()["Items"] if "correct_pick" in i]
    assert len(scored) == 1


def test_no_retrospective_trigger_when_arn_unset(aws_env, tables):
    from scoring.lambda_handler import lambda_handler

    with patch("scoring.lambda_handler.aggregate_round"), \
         patch("scoring.lambda_handler.boto3.client") as mock_client:
        lambda_handler({"matchId": MATCH_ID, "round": 12, "season": 2026}, {})

    mock_client.assert_not_called()


# --- season / market aggregation calls -------------------------------------------


def test_season_aggregations_fire_once_per_handler_run(aws_env, tables):
    from scoring.lambda_handler import lambda_handler

    with patch("scoring.lambda_handler.aggregate_round") as mock_round, \
         patch("scoring.lambda_handler.aggregate_season") as mock_season:
        lambda_handler({"matchId": MATCH_ID, "round": 12, "season": 2026}, {})

    mock_round.assert_called_once_with(12, 2026, ANY, ANY)
    mock_season.assert_called_once_with(2026, ANY, ANY)


def test_market_aggregation_runs_when_odds_table_configured(aws_env, tables, monkeypatch):
    monkeypatch.setenv("ODDS_TABLE", "odds")
    from scoring.lambda_handler import lambda_handler

    with patch("scoring.lambda_handler.aggregate_round"), \
         patch("scoring.lambda_handler.aggregate_market_season") as mock_market:
        lambda_handler({"matchId": MATCH_ID, "round": 12, "season": 2026}, {})

    mock_market.assert_called_once_with(2026, ANY, ANY, ANY)


def test_market_aggregation_failure_does_not_break_scoring(aws_env, tables, monkeypatch, caplog):
    monkeypatch.setenv("ODDS_TABLE", "odds")
    from scoring.lambda_handler import lambda_handler

    with patch("scoring.lambda_handler.aggregate_round"), \
         patch(
             "scoring.lambda_handler.aggregate_market_season",
             side_effect=RuntimeError("boom"),
         ), \
         caplog.at_level("WARNING"):
        resp = lambda_handler({"matchId": MATCH_ID, "round": 12, "season": 2026}, {})

    assert resp == {"status": "OK", "matchId": MATCH_ID}
    assert "Market accuracy aggregation failed" in caplog.text


def test_market_aggregation_skipped_when_odds_table_unset(aws_env, tables):
    from scoring.lambda_handler import lambda_handler

    with patch("scoring.lambda_handler.aggregate_round"), \
         patch("scoring.lambda_handler.aggregate_market_season") as mock_market:
        lambda_handler({"matchId": MATCH_ID, "round": 12, "season": 2026}, {})

    mock_market.assert_not_called()


# --- early-return / error branches ---------------------------------------------------


def test_scoring_skipped_when_result_not_ready(aws_env, tables):
    """No result row yet -> ResultNotReady -> NO_RESULT, nothing scored or aggregated."""
    from scoring.lambda_handler import lambda_handler

    tables.Table(RESULTS_TABLE).delete_item(
        Key={"matchId": MATCH_ID, "scoredAt": "2026-05-16T11:30:00Z"}
    )
    with patch("scoring.lambda_handler.aggregate_round") as mock_round:
        resp = lambda_handler({"matchId": MATCH_ID, "round": 12, "season": 2026}, {})

    assert resp == {"status": "NO_RESULT", "matchId": MATCH_ID}
    mock_round.assert_not_called()
    scored = [i for i in tables.Table(RESULTS_TABLE).scan()["Items"] if "correct_pick" in i]
    assert scored == []


def test_scoring_reraises_unexpected_errors(aws_env, tables):
    from scoring.lambda_handler import lambda_handler

    with patch(
        "scoring.lambda_handler.score_prediction", side_effect=RuntimeError("kaboom")
    ):
        with pytest.raises(RuntimeError, match="kaboom"):
            lambda_handler({"matchId": MATCH_ID, "round": 12, "season": 2026}, {})


# --- _get_kickoff resilience -------------------------------------------------------


def test_get_kickoff_swallows_teams_table_error(aws_env, tables, monkeypatch, caplog):
    """A broken teams-table lookup degrades to kickoff=None, it must not crash scoring."""
    monkeypatch.setenv("TEAMS_TABLE", "teams-does-not-exist")
    from scoring.lambda_handler import lambda_handler

    with patch("scoring.lambda_handler.aggregate_round"), caplog.at_level("WARNING"):
        resp = lambda_handler({"matchId": MATCH_ID, "round": 12, "season": 2026}, {})

    assert resp == {"status": "OK", "matchId": MATCH_ID}
    assert "teams_table.get_item failed" in caplog.text


def test_get_kickoff_warns_when_row_has_no_kickoff_value(aws_env, tables, monkeypatch, caplog):
    monkeypatch.setenv("TEAMS_TABLE", "teams")
    teams_tbl = tables.create_table(
        TableName="teams",
        KeySchema=[{"AttributeName": "teamId", "KeyType": "HASH"},
                   {"AttributeName": "round", "KeyType": "RANGE"}],
        AttributeDefinitions=[{"AttributeName": "teamId", "AttributeType": "S"},
                              {"AttributeName": "round", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    # draw row exists but carries no kickOff attribute
    teams_tbl.put_item(Item={"teamId": f"{MATCH_ID}#home", "round": "12"})
    from scoring.lambda_handler import lambda_handler

    with patch("scoring.lambda_handler.aggregate_round"), caplog.at_level("WARNING"):
        resp = lambda_handler({"matchId": MATCH_ID, "round": 12, "season": 2026}, {})

    assert resp == {"status": "OK", "matchId": MATCH_ID}
    assert "no kickOff value found" in caplog.text
