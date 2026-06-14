from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

from scoring.odds_accuracy import find_outlier, score_market

ODDS_TABLE = "odds"
RESULTS_TABLE = "results"
PREDICTIONS_TABLE = "predictions"
MATCH_ID = "round-12-panthers-v-broncos"


def _put_odds(table, match_id=MATCH_ID, market_favourite="Panthers",
              market_margin=8.5, home_odds=1.55, away_odds=2.45,
              implied_home=0.612, implied_away=0.388,
              scraped_at="2026-05-16T08:00:00Z", round_number=12, season=2026):
    table.put_item(Item={
        "matchId": match_id,
        "scrapedAt": scraped_at,
        "market_favourite": market_favourite,
        "market_margin": Decimal(str(market_margin)),
        "home_odds": Decimal(str(home_odds)),
        "away_odds": Decimal(str(away_odds)),
        "implied_home_prob": Decimal(str(implied_home)),
        "implied_away_prob": Decimal(str(implied_away)),
        "roundNumber": round_number,
        "season": season,
    })


def _put_result(table, match_id=MATCH_ID, winner="Panthers", margin=12,
                home_score=26, away_score=14, round_number=12, season=2026):
    table.put_item(Item={
        "matchId": match_id,
        "scoredAt": "2026-05-17T11:30:00Z",
        "winner": winner,
        "homeTeam": "Panthers",
        "awayTeam": "Broncos",
        "homeScore": home_score,
        "awayScore": away_score,
        "margin": margin,
        "correct_pick": True,
        "roundNumber": round_number,
        "season": season,
    })


def _put_prediction(table, match_id=MATCH_ID, predicted_winner="Panthers",
                    predicted_margin=10, confidence="HIGH"):
    table.put_item(Item={
        "matchId": match_id,
        "generatedAt": "2026-05-15T20:00:00Z",
        "predicted_winner": predicted_winner,
        "predicted_margin": predicted_margin,
        "confidence": confidence,
        "status": "OK",
    })


@pytest.fixture
def tables():
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="ap-southeast-2")
        client = boto3.client("dynamodb", region_name="ap-southeast-2")
        for name, pk, sk in [
            (ODDS_TABLE, "matchId", "scrapedAt"),
            (RESULTS_TABLE, "matchId", "scoredAt"),
            (PREDICTIONS_TABLE, "matchId", "generatedAt"),
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
        odds_tbl = ddb.Table(ODDS_TABLE)
        results_tbl = ddb.Table(RESULTS_TABLE)
        preds_tbl = ddb.Table(PREDICTIONS_TABLE)
        yield odds_tbl, results_tbl, preds_tbl


class TestScoreMarket:
    def test_correct_pick_when_favourite_wins(self, tables):
        odds_tbl, results_tbl, _ = tables
        _put_odds(odds_tbl, market_favourite="Panthers", market_margin=8.5,
                  implied_home=0.612, implied_away=0.388)
        _put_result(results_tbl, winner="Panthers", margin=12)

        result = score_market(MATCH_ID, odds_tbl, results_tbl)

        assert result.correct_pick is True
        assert result.match_id == MATCH_ID

    def test_wrong_pick_when_underdog_wins(self, tables):
        odds_tbl, results_tbl, _ = tables
        _put_odds(odds_tbl, market_favourite="Panthers", market_margin=8.5,
                  implied_home=0.612, implied_away=0.388)
        _put_result(results_tbl, winner="Broncos", margin=4)

        result = score_market(MATCH_ID, odds_tbl, results_tbl)

        assert result.correct_pick is False

    def test_margin_error_calculation(self, tables):
        odds_tbl, results_tbl, _ = tables
        _put_odds(odds_tbl, market_margin=8.5)
        _put_result(results_tbl, winner="Panthers", margin=12)

        result = score_market(MATCH_ID, odds_tbl, results_tbl)

        assert result.predicted_margin_error == 4  # |12 - 8| = 4 (rounded to int)

    def test_within_6_pts_threshold(self, tables):
        odds_tbl, results_tbl, _ = tables
        _put_odds(odds_tbl, market_margin=8.5)
        _put_result(results_tbl, winner="Panthers", margin=12)  # diff = 3.5 → within 6

        result = score_market(MATCH_ID, odds_tbl, results_tbl)

        assert result.within_6_pts is True

    def test_outside_6_pts_threshold(self, tables):
        odds_tbl, results_tbl, _ = tables
        _put_odds(odds_tbl, market_margin=8.5)
        _put_result(results_tbl, winner="Panthers", margin=20)  # diff = 11.5 → outside 6

        result = score_market(MATCH_ID, odds_tbl, results_tbl)

        assert result.within_6_pts is False

    def test_brier_component_correct_pick(self, tables):
        odds_tbl, results_tbl, _ = tables
        # implied_home = 0.7 (home team wins) → brier = (0.7 - 1)^2 = 0.09
        _put_odds(odds_tbl, market_favourite="Panthers", implied_home=0.7, implied_away=0.3)
        _put_result(results_tbl, winner="Panthers", margin=8)

        result = score_market(MATCH_ID, odds_tbl, results_tbl)

        assert abs(result.brier_component - 0.09) < 0.001

    def test_brier_component_wrong_pick(self, tables):
        odds_tbl, results_tbl, _ = tables
        # implied_home = 0.7 but away wins → brier = (0.7 - 0)^2 = 0.49
        _put_odds(odds_tbl, market_favourite="Panthers", implied_home=0.7, implied_away=0.3)
        _put_result(results_tbl, winner="Broncos", margin=4)

        result = score_market(MATCH_ID, odds_tbl, results_tbl)

        assert abs(result.brier_component - 0.49) < 0.001

    def test_uses_most_recent_odds_when_multiple_exist(self, tables):
        odds_tbl, results_tbl, _ = tables
        _put_odds(odds_tbl, market_favourite="Broncos", scraped_at="2026-05-14T08:00:00Z")
        _put_odds(odds_tbl, market_favourite="Panthers", scraped_at="2026-05-16T16:00:00Z")
        _put_result(results_tbl, winner="Panthers", margin=6)

        result = score_market(MATCH_ID, odds_tbl, results_tbl)

        assert result.correct_pick is True  # most recent odds had Panthers as favourite

    def test_raises_when_no_odds(self, tables):
        odds_tbl, results_tbl, _ = tables
        _put_result(results_tbl, winner="Panthers", margin=6)

        with pytest.raises(ValueError, match="No odds found"):
            score_market(MATCH_ID, odds_tbl, results_tbl)

    def test_raises_when_no_result(self, tables):
        odds_tbl, results_tbl, _ = tables
        _put_odds(odds_tbl)

        with pytest.raises(IndexError):
            score_market(MATCH_ID, odds_tbl, results_tbl)


class TestFindOutlier:
    def test_no_outlier_when_both_agree(self, tables):
        odds_tbl, _, preds_tbl = tables
        _put_odds(odds_tbl, market_favourite="Panthers", market_margin=10.0)
        _put_prediction(preds_tbl, predicted_winner="Panthers", predicted_margin=10)

        result = find_outlier(MATCH_ID, odds_tbl, preds_tbl)

        assert result is None

    def test_outlier_when_winner_disagrees(self, tables):
        odds_tbl, _, preds_tbl = tables
        _put_odds(odds_tbl, market_favourite="Panthers", market_margin=10.0)
        _put_prediction(preds_tbl, predicted_winner="Broncos", predicted_margin=4)

        result = find_outlier(MATCH_ID, odds_tbl, preds_tbl)

        assert result is not None
        assert result["reason"] == "winner_disagrees"

    def test_outlier_when_margin_differs_by_more_than_6(self, tables):
        odds_tbl, _, preds_tbl = tables
        _put_odds(odds_tbl, market_favourite="Panthers", market_margin=10.0)
        _put_prediction(preds_tbl, predicted_winner="Panthers", predicted_margin=18)

        result = find_outlier(MATCH_ID, odds_tbl, preds_tbl)

        assert result is not None
        assert result["reason"] == "margin_diverges"

    def test_no_outlier_when_margin_within_6(self, tables):
        odds_tbl, _, preds_tbl = tables
        _put_odds(odds_tbl, market_favourite="Panthers", market_margin=10.0)
        _put_prediction(preds_tbl, predicted_winner="Panthers", predicted_margin=14)

        result = find_outlier(MATCH_ID, odds_tbl, preds_tbl)

        assert result is None  # diff = 4, within threshold

    def test_returns_none_when_no_odds(self, tables):
        odds_tbl, _, preds_tbl = tables
        _put_prediction(preds_tbl, predicted_winner="Panthers", predicted_margin=10)

        result = find_outlier(MATCH_ID, odds_tbl, preds_tbl)

        assert result is None

    def test_returns_none_when_no_prediction(self, tables):
        odds_tbl, _, preds_tbl = tables
        _put_odds(odds_tbl, market_favourite="Panthers", market_margin=10.0)

        result = find_outlier(MATCH_ID, odds_tbl, preds_tbl)

        assert result is None
