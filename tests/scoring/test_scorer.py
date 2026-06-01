import boto3
import pytest
from decimal import Decimal
from moto import mock_aws
from scoring.scorer import score_prediction, ScoredResult

PRED_TABLE = "predictions"
RESULTS_TABLE = "results"
MATCH_ID = "panthers-v-broncos-20260515"


def _seed_prediction(table, winner="Panthers", margin=10, confidence="HIGH"):
    table.put_item(Item={
        "matchId": MATCH_ID,
        "generatedAt": "2026-05-15T20:00:00Z",
        "predicted_winner": winner,
        "predicted_margin": margin,
        "confidence": confidence,
        "status": "OK",
    })


def _seed_result(table, home_score=24, away_score=18):
    table.put_item(Item={
        "matchId": MATCH_ID,
        "scoredAt": "2026-05-16T11:30:00Z",
        "homeTeam": "Panthers",
        "awayTeam": "Broncos",
        "homeScore": home_score,
        "awayScore": away_score,
        "winner": "Panthers" if home_score > away_score else "Broncos",
        "margin": abs(home_score - away_score),
        "matchState": "FullTime",
    })


@pytest.fixture
def tables():
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="ap-southeast-2")
        client = boto3.client("dynamodb", region_name="ap-southeast-2")
        for name, pk, sk in [
            (PRED_TABLE, "matchId", "generatedAt"),
            (RESULTS_TABLE, "matchId", "scoredAt"),
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
        pred_tbl = ddb.Table(PRED_TABLE)
        results_tbl = ddb.Table(RESULTS_TABLE)
        yield pred_tbl, results_tbl


def test_correct_pick(tables):
    pred_tbl, results_tbl = tables
    _seed_prediction(pred_tbl, winner="Panthers")
    _seed_result(results_tbl, home_score=24, away_score=18)
    result = score_prediction(MATCH_ID, results_tbl, pred_tbl)
    assert isinstance(result, ScoredResult)
    assert result.correct_pick is True


def test_incorrect_pick(tables):
    pred_tbl, results_tbl = tables
    _seed_prediction(pred_tbl, winner="Broncos")
    _seed_result(results_tbl, home_score=24, away_score=18)
    result = score_prediction(MATCH_ID, results_tbl, pred_tbl)
    assert result.correct_pick is False


def test_margin_error(tables):
    pred_tbl, results_tbl = tables
    _seed_prediction(pred_tbl, winner="Panthers", margin=10)
    _seed_result(results_tbl, home_score=24, away_score=18)  # actual margin 6
    result = score_prediction(MATCH_ID, results_tbl, pred_tbl)
    assert result.predicted_margin_error == 4  # |10 - 6|


def test_within_thresholds(tables):
    pred_tbl, results_tbl = tables
    _seed_prediction(pred_tbl, winner="Panthers", margin=10)
    _seed_result(results_tbl, home_score=24, away_score=18)
    result = score_prediction(MATCH_ID, results_tbl, pred_tbl)
    assert result.within_6_pts is True    # error is 4, which is ≤6
    assert result.within_12_pts is True


def test_brier_high_confidence(tables):
    pred_tbl, results_tbl = tables
    _seed_prediction(pred_tbl, winner="Panthers", confidence="HIGH")
    _seed_result(results_tbl, home_score=24, away_score=18)
    result = score_prediction(MATCH_ID, results_tbl, pred_tbl)
    # HIGH = p=0.85, correct=1 → (0.85-1)^2 = 0.0225
    assert result.brier_component == pytest.approx(0.0225)


def test_skips_failed_prediction_uses_latest_ok(tables):
    """Scorer must skip FAILED records and use the most recent OK prediction."""
    pred_tbl, results_tbl = tables
    # Seed an OK prediction first
    _seed_prediction(pred_tbl, winner="Panthers", confidence="HIGH")
    # Seed a later FAILED record (no predicted_winner)
    pred_tbl.put_item(Item={
        "matchId": MATCH_ID,
        "generatedAt": "2026-05-16T08:00:00Z",  # later than OK above
        "status": "FAILED",
        "error": "Agent produced non-JSON output",
    })
    _seed_result(results_tbl, home_score=24, away_score=18)
    result = score_prediction(MATCH_ID, results_tbl, pred_tbl)
    assert result.correct_pick is True
