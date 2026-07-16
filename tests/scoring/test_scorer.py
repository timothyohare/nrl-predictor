
import boto3
import pytest
from moto import mock_aws

from scoring.scorer import ScoredResult, score_prediction

PRED_TABLE = "predictions"
RESULTS_TABLE = "results"
MATCH_ID = "panthers-v-broncos-20260515"


def _seed_prediction(table, winner="Panthers", margin=10, confidence="HIGH", **extra):
    table.put_item(Item={
        "matchId": MATCH_ID,
        "generatedAt": "2026-05-15T20:00:00Z",
        "predicted_winner": winner,
        "predicted_margin": margin,
        "confidence": confidence,
        "status": "OK",
        **extra,
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
    assert result.match_id == MATCH_ID
    assert result.confidence == "HIGH"


def test_incorrect_pick(tables):
    pred_tbl, results_tbl = tables
    _seed_prediction(pred_tbl, winner="Broncos")
    _seed_result(results_tbl, home_score=24, away_score=18)
    result = score_prediction(MATCH_ID, results_tbl, pred_tbl)
    assert result.correct_pick is False
    # HIGH = p=0.85, incorrect=0 → (0.85-0)^2 — a wrong confident pick must cost dearly
    assert result.brier_component == pytest.approx(0.7225)


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


@pytest.mark.parametrize("predicted_margin,within6,within12", [
    (12, True, True),    # error 6 — exactly on the 6-pt boundary (inclusive)
    (13, False, True),   # error 7 — just outside 6
    (18, False, True),   # error 12 — exactly on the 12-pt boundary (inclusive)
    (19, False, False),  # error 13 — just outside 12
])
def test_margin_threshold_boundaries(tables, predicted_margin, within6, within12):
    """The ≤6 / ≤12 buckets are inclusive at the boundary."""
    pred_tbl, results_tbl = tables
    _seed_prediction(pred_tbl, winner="Panthers", margin=predicted_margin)
    _seed_result(results_tbl, home_score=24, away_score=18)  # actual margin 6
    result = score_prediction(MATCH_ID, results_tbl, pred_tbl)
    assert result.predicted_margin_error == abs(predicted_margin - 6)
    assert result.within_6_pts is within6
    assert result.within_12_pts is within12


def test_brier_high_confidence(tables):
    pred_tbl, results_tbl = tables
    _seed_prediction(pred_tbl, winner="Panthers", confidence="HIGH")
    _seed_result(results_tbl, home_score=24, away_score=18)
    result = score_prediction(MATCH_ID, results_tbl, pred_tbl)
    # HIGH = p=0.85, correct=1 → (0.85-1)^2 = 0.0225
    assert result.brier_component == pytest.approx(0.0225)


def test_defaults_for_missing_optional_fields(tables):
    """Margin defaults to 0, confidence to MEDIUM, prompt_version to 'unknown' — old rows
    predate these fields and must still score."""
    pred_tbl, results_tbl = tables
    pred_tbl.put_item(Item={
        "matchId": MATCH_ID,
        "generatedAt": "2026-05-15T20:00:00Z",
        "predicted_winner": "Panthers",
        "status": "OK",
    })
    _seed_result(results_tbl, home_score=24, away_score=18)  # actual margin 6
    result = score_prediction(MATCH_ID, results_tbl, pred_tbl)
    assert result.predicted_margin_error == 6  # |0 - 6|
    assert result.confidence == "MEDIUM"
    assert result.prompt_version == "unknown"


def test_prompt_version_carried_through(tables):
    pred_tbl, results_tbl = tables
    _seed_prediction(pred_tbl, winner="Panthers", prompt_version="v1.2")
    _seed_result(results_tbl, home_score=24, away_score=18)
    assert score_prediction(MATCH_ID, results_tbl, pred_tbl).prompt_version == "v1.2"


def test_unrecognised_confidence_uses_default_probability(tables):
    pred_tbl, results_tbl = tables
    _seed_prediction(pred_tbl, winner="Panthers", confidence="WILD")
    _seed_result(results_tbl, home_score=24, away_score=18)
    result = score_prediction(MATCH_ID, results_tbl, pred_tbl)
    # unknown label falls back to p=0.65, correct=1 → (0.65-1)^2
    assert result.brier_component == pytest.approx(0.1225)


def test_scores_against_most_recent_result_row(tables):
    """Two result rows for one match (e.g. a re-scrape correcting a score): the newest wins."""
    pred_tbl, results_tbl = tables
    _seed_prediction(pred_tbl, winner="Panthers", margin=10)
    results_tbl.put_item(Item={  # stale early row with the wrong winner
        "matchId": MATCH_ID,
        "scoredAt": "2026-05-16T09:00:00Z",
        "homeTeam": "Panthers",
        "awayTeam": "Broncos",
        "homeScore": 10,
        "awayScore": 20,
        "winner": "Broncos",
        "margin": 10,
        "matchState": "FullTime",
    })
    _seed_result(results_tbl, home_score=24, away_score=18)  # corrected row, 2.5h later
    result = score_prediction(MATCH_ID, results_tbl, pred_tbl)
    assert result.correct_pick is True
    assert result.predicted_margin_error == 4  # against the corrected margin of 6


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


def test_result_not_ready_when_no_result_row(tables):
    """A prediction with no result row must raise ResultNotReady (caught + skipped by the
    handler), not crash with IndexError — this 500'd the scoring lambda on 2026-06-21."""
    from scoring.scorer import ResultNotReady
    pred_tbl, results_tbl = tables
    _seed_prediction(pred_tbl, winner="Panthers")
    # no result seeded; the message must name the match for the handler's log line
    with pytest.raises(ResultNotReady, match=MATCH_ID):
        score_prediction(MATCH_ID, results_tbl, pred_tbl)


def test_no_ok_prediction_raises_with_match_id(tables):
    pred_tbl, results_tbl = tables
    pred_tbl.put_item(Item={
        "matchId": MATCH_ID,
        "generatedAt": "2026-05-16T08:00:00Z",
        "status": "FAILED",
        "error": "Agent produced non-JSON output",
    })
    _seed_result(results_tbl, home_score=24, away_score=18)
    with pytest.raises(ValueError, match=MATCH_ID):
        score_prediction(MATCH_ID, results_tbl, pred_tbl)


def test_scores_last_prediction_before_kickoff(tables):
    """A post-kickoff regeneration must NOT be scored — pick the last pre-kickoff prediction."""
    from common.teams import to_slug  # noqa: F401 (ensure import path works)
    pred_tbl, results_tbl = tables
    ko = "2026-05-16T08:00:00Z"
    # pre-kickoff forecast: Broncos (wrong); post-kickoff hindsight: Panthers (right)
    pred_tbl.put_item(Item={"matchId": MATCH_ID, "generatedAt": "2026-05-14T09:00:00Z",
                            "predicted_winner": "Broncos", "predicted_margin": 4,
                            "confidence": "MEDIUM", "status": "OK"})
    pred_tbl.put_item(Item={"matchId": MATCH_ID, "generatedAt": "2026-05-16T20:00:00Z",
                            "predicted_winner": "Panthers", "predicted_margin": 10,
                            "confidence": "HIGH", "status": "OK"})
    _seed_result(results_tbl, home_score=24, away_score=18)  # Panthers win
    scored = score_prediction(MATCH_ID, results_tbl, pred_tbl, kickoff=ko)
    assert scored.correct_pick is False  # scored pre-KO 'Broncos', not hindsight 'Panthers'
