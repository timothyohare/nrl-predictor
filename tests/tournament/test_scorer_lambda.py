"""Tests for v1/tournament/scorer_lambda.py — the post-match Lambda that scores
every prompt variant for a round and refreshes the season aggregation.

The whole handler body was untested (file was at 0% line coverage). This is the
path that silently wrote zero `variant_metrics` rows in rounds 25-26, so it's
worth a regression lock on the contract: env vars -> tables, `score_round` then
`aggregate_variant_season`, and the `{"status": "ok", ...}` response shape.
"""
import boto3
import pytest
from moto import mock_aws

from v1.tournament import scorer_lambda

SIM_TABLE = "simulation_predictions"
RESULTS_TABLE = "results"
VARIANT_METRICS_TABLE = "variant_metrics"

MATCH_ID_1 = "round-12-panthers-v-broncos"
MATCH_ID_2 = "round-12-storm-v-roosters"


def _put_sim_prediction(table, match_id, variant_id, predicted_winner, predicted_margin=10,
                        confidence="HIGH", round_number=12, season=2026):
    table.put_item(Item={
        "pk": f"{match_id}#{variant_id}",
        "generatedAt": "2026-05-31T08:00:00Z",
        "matchId": match_id,
        "variantId": variant_id,
        "predicted_winner": predicted_winner,
        "predicted_margin": predicted_margin,
        "confidence": confidence,
        "roundNumber": round_number,
        "season": season,
    })


def _put_result(table, match_id, winner, margin=8, round_number=12, season=2026):
    table.put_item(Item={
        "matchId": match_id,
        "scoredAt": "2026-06-01T11:30:00Z",
        "winner": winner,
        "margin": margin,
        "roundNumber": round_number,
        "season": season,
    })


@pytest.fixture
def tables(monkeypatch):
    with mock_aws():
        client = boto3.client("dynamodb", region_name="ap-southeast-2")
        for name, pk, sk in [
            (SIM_TABLE, "pk", "generatedAt"),
            (RESULTS_TABLE, "matchId", "scoredAt"),
            (VARIANT_METRICS_TABLE, "variantId", "period"),
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
        monkeypatch.setenv("SIMULATION_PREDICTIONS_TABLE", SIM_TABLE)
        monkeypatch.setenv("RESULTS_TABLE", RESULTS_TABLE)
        monkeypatch.setenv("VARIANT_METRICS_TABLE", VARIANT_METRICS_TABLE)
        ddb = boto3.resource("dynamodb", region_name="ap-southeast-2")
        yield ddb.Table(SIM_TABLE), ddb.Table(RESULTS_TABLE), ddb.Table(VARIANT_METRICS_TABLE)


def test_happy_path_scores_variants_and_aggregates_season(tables, mocker):
    sim_tbl, results_tbl, metrics_tbl = tables
    _put_sim_prediction(sim_tbl, MATCH_ID_1, "baseline", "Panthers")
    _put_sim_prediction(sim_tbl, MATCH_ID_2, "baseline", "Storm")
    _put_sim_prediction(sim_tbl, MATCH_ID_1, "heavy-home-advantage", "Broncos")
    _put_result(results_tbl, MATCH_ID_1, "Panthers", margin=12)
    _put_result(results_tbl, MATCH_ID_2, "Storm", margin=6)

    score_spy = mocker.spy(scorer_lambda, "score_round")
    agg_spy = mocker.spy(scorer_lambda, "aggregate_variant_season")

    out = scorer_lambda.lambda_handler({"round": 12, "season": 2026}, None)

    assert out == {"status": "ok", "round": 12, "variants_scored": 2}
    assert score_spy.call_count == 1
    assert agg_spy.call_count == 1
    # Both the per-round and the season rows are persisted for a scored variant.
    assert "Item" in metrics_tbl.get_item(
        Key={"variantId": "baseline", "period": "2026-round-12"})
    assert "Item" in metrics_tbl.get_item(
        Key={"variantId": "baseline", "period": "2026-season"})


def test_missing_env_var_raises_key_error(tables, monkeypatch):
    # Contract: an un-provisioned deployment fails loudly, not silently.
    monkeypatch.delenv("VARIANT_METRICS_TABLE", raising=False)

    with pytest.raises(KeyError):
        scorer_lambda.lambda_handler({"round": 12, "season": 2026}, None)


def test_round_with_no_sim_rows_scores_zero_variants(tables):
    _, results_tbl, metrics_tbl = tables
    _put_result(results_tbl, MATCH_ID_1, "Panthers", margin=12)  # result but no sim preds

    out = scorer_lambda.lambda_handler({"round": 12, "season": 2026}, None)

    assert out == {"status": "ok", "round": 12, "variants_scored": 0}
    assert metrics_tbl.scan()["Items"] == []
