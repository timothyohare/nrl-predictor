"""Tests for the main-path stats predictor (v1/orchestrator/stats_predictor.py) —
the Phase 3 cutover from the Claude agent to the local Elo + Monte Carlo model.
See docs/plans/10-elo-monte-carlo-predictor.md.
"""
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

from scrapers.shared.models import Match

MODEL_ID = "stats-elo-v1"


@pytest.fixture
def tables():
    with mock_aws():
        client = boto3.client("dynamodb", region_name="ap-southeast-2")
        client.create_table(
            TableName="predictions",
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
        client.create_table(
            TableName="results",
            KeySchema=[
                {"AttributeName": "matchId", "KeyType": "HASH"},
                {"AttributeName": "scoredAt", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "matchId", "AttributeType": "S"},
                {"AttributeName": "scoredAt", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        ddb = boto3.resource("dynamodb", region_name="ap-southeast-2")
        yield ddb.Table("predictions"), ddb.Table("results")


def _matches():
    return [
        Match(
            match_id="round-13-panthers-v-broncos",
            home_team="Panthers",
            away_team="Broncos",
            venue="BlueBet Stadium",
            round_number=13,
            kick_off="2026-06-01T09:00:00Z",
            match_state="Pre",
            match_centre_url="/draw/nrl-premiership/2026/round-13/panthers-v-broncos/",
        ),
        Match(
            match_id="round-13-storm-v-roosters",
            home_team="Storm",
            away_team="Roosters",
            venue="AAMI Park",
            round_number=13,
            kick_off="2026-06-01T23:00:00Z",
            match_state="Pre",
            match_centre_url="/draw/nrl-premiership/2026/round-13/storm-v-roosters/",
        ),
    ]


class TestPredictRound:
    def test_writes_one_ok_prediction_per_match(self, tables):
        from v1.orchestrator.stats_predictor import predict_round

        predictions_table, results_table = tables
        predicted = predict_round(_matches(), round_number=13, season=2026,
                                   predictions_table=predictions_table, results_table=results_table)

        assert predicted == ["round-13-panthers-v-broncos", "round-13-storm-v-roosters"]
        items = predictions_table.scan()["Items"]
        assert len(items) == 2
        for item in items:
            assert item["status"] == "OK"
            assert item["staleness_flag"] is False
            assert item["model_used"] == MODEL_ID
            assert item["prompt_version"] == MODEL_ID
            assert item["roundNumber"] == 13
            assert item["confidence"] in ("HIGH", "MEDIUM", "LOW")
            assert len(item["key_factors"]) >= 2
            assert item["generation"] == 1
            assert 0 <= item["margin_low"] < item["margin_high"]
            assert item["predicted_margin"] <= item["margin_high"]

    def test_predicted_winner_is_one_of_the_two_teams(self, tables):
        from v1.orchestrator.stats_predictor import predict_round

        predictions_table, results_table = tables
        predict_round(_matches()[:1], round_number=13, season=2026,
                       predictions_table=predictions_table, results_table=results_table)

        item = predictions_table.scan()["Items"][0]
        assert item["predicted_winner"] in ("panthers", "broncos")

    def test_generation_increments_across_runs(self, tables):
        from v1.orchestrator.stats_predictor import predict_round

        predictions_table, results_table = tables
        match = _matches()[:1]
        predict_round(match, round_number=13, season=2026,
                       predictions_table=predictions_table, results_table=results_table)
        predict_round(match, round_number=13, season=2026,
                       predictions_table=predictions_table, results_table=results_table)

        items = predictions_table.query(
            KeyConditionExpression="matchId = :m",
            ExpressionAttributeValues={":m": "round-13-panthers-v-broncos"},
        )["Items"]
        assert sorted(i["generation"] for i in items) == [1, 2]

    def test_one_match_failing_does_not_block_the_others(self, tables):
        from common.stats_model.predictor import predict_match as real_predict_match
        from v1.orchestrator.stats_predictor import predict_round

        predictions_table, results_table = tables

        def flaky_predict(home, away, *args, **kwargs):
            if home == "panthers":
                raise ValueError("boom")
            return real_predict_match(home, away, *args, **kwargs)

        with patch("v1.orchestrator.stats_predictor.predict_match", side_effect=flaky_predict):
            predicted = predict_round(_matches(), round_number=13, season=2026,
                                       predictions_table=predictions_table, results_table=results_table)

        assert predicted == ["round-13-storm-v-roosters"]
        items = {i["matchId"]: i for i in predictions_table.scan()["Items"]}
        assert items["round-13-panthers-v-broncos"]["status"] == "FAILED"
        assert items["round-13-storm-v-roosters"]["status"] == "OK"

    def test_no_agent_import(self):
        # Sanity guard for the whole point of the cutover: this module must not
        # touch the agent/Claude at all.
        import v1.orchestrator.stats_predictor as mod
        assert "run_agent" not in dir(mod)


@pytest.fixture
def teams_table(tables):
    """A `teams` table in the same already-active mock_aws context as `tables`."""
    client = boto3.client("dynamodb", region_name="ap-southeast-2")
    client.create_table(
        TableName="teams",
        KeySchema=[
            {"AttributeName": "teamId", "KeyType": "HASH"},
            {"AttributeName": "round", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "teamId", "AttributeType": "S"},
            {"AttributeName": "round", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    return boto3.resource("dynamodb", region_name="ap-southeast-2").Table("teams")


class TestPredictRoundSpineSignal:
    """docs/plans/11-team-sheet-injury-weather-signals.md, Phase 2."""

    def test_spine_changed_home_is_reflected_in_key_factors(self, tables, teams_table):
        from v1.orchestrator.stats_predictor import predict_round

        predictions_table, results_table = tables
        teams_table.put_item(Item={
            "teamId": "round-13-panthers-v-broncos", "round": "13",
            "spine_changed_home": True, "spine_changed_away": False,
        })

        predict_round(_matches()[:1], round_number=13, season=2026,
                       predictions_table=predictions_table, results_table=results_table,
                       teams_table=teams_table)

        item = predictions_table.scan()["Items"][0]
        assert any("adjusted" in f for f in item["key_factors"])

    def test_no_row_for_the_match_is_a_no_op(self, tables, teams_table):
        from v1.orchestrator.stats_predictor import predict_round

        predictions_table, results_table = tables
        # teams_table exists but has no item for this match/round — must fail
        # open (no exception, no adjustment), same as a missing team sheet.
        predict_round(_matches()[:1], round_number=13, season=2026,
                       predictions_table=predictions_table, results_table=results_table,
                       teams_table=teams_table)

        item = predictions_table.scan()["Items"][0]
        assert not any("adjusted" in f for f in item["key_factors"])

    def test_omitting_teams_table_entirely_is_backward_compatible(self, tables):
        from v1.orchestrator.stats_predictor import predict_round

        predictions_table, results_table = tables
        predicted = predict_round(_matches()[:1], round_number=13, season=2026,
                                   predictions_table=predictions_table, results_table=results_table)

        assert predicted == ["round-13-panthers-v-broncos"]
        assert predictions_table.scan()["Items"][0]["status"] == "OK"


@pytest.fixture
def injuries_table(tables):
    """An `injuries` table in the same already-active mock_aws context as `tables`."""
    client = boto3.client("dynamodb", region_name="ap-southeast-2")
    client.create_table(
        TableName="injuries",
        KeySchema=[
            {"AttributeName": "pk", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    return boto3.resource("dynamodb", region_name="ap-southeast-2").Table("injuries")


class TestPredictRoundInjurySignal:
    """docs/plans/11-team-sheet-injury-weather-signals.md, Phase 3."""

    def test_spine_player_ruled_out_is_reflected_in_key_factors(self, tables, teams_table, injuries_table):
        from v1.orchestrator.stats_predictor import predict_round

        predictions_table, results_table = tables
        teams_table.put_item(Item={
            "teamId": "round-13-panthers-v-broncos", "round": "13",
            "homePlayers": [{"jersey_number": 7, "first_name": "Test", "last_name": "Halfback"}],
            "awayPlayers": [],
            "spine_changed_home": False, "spine_changed_away": False,
        })
        injuries_table.put_item(Item={
            "pk": "injury#panthers#test-halfback", "sk": "2026-06-01T00:00:00Z",
            "player": "Test Halfback", "team": "panthers", "status": "out", "detail": "",
        })

        predict_round(_matches()[:1], round_number=13, season=2026,
                       predictions_table=predictions_table, results_table=results_table,
                       teams_table=teams_table, injuries_table=injuries_table)

        item = predictions_table.scan()["Items"][0]
        assert any("adjusted" in f for f in item["key_factors"])

    def test_no_matching_mention_is_a_no_op(self, tables, teams_table, injuries_table):
        from v1.orchestrator.stats_predictor import predict_round

        predictions_table, results_table = tables
        teams_table.put_item(Item={
            "teamId": "round-13-panthers-v-broncos", "round": "13",
            "homePlayers": [{"jersey_number": 7, "first_name": "Test", "last_name": "Halfback"}],
            "awayPlayers": [],
            "spine_changed_home": False, "spine_changed_away": False,
        })

        predict_round(_matches()[:1], round_number=13, season=2026,
                       predictions_table=predictions_table, results_table=results_table,
                       teams_table=teams_table, injuries_table=injuries_table)

        item = predictions_table.scan()["Items"][0]
        assert not any("adjusted" in f for f in item["key_factors"])

    def test_omitting_injuries_table_entirely_is_backward_compatible(self, tables, teams_table):
        from v1.orchestrator.stats_predictor import predict_round

        predictions_table, results_table = tables
        predicted = predict_round(_matches()[:1], round_number=13, season=2026,
                                   predictions_table=predictions_table, results_table=results_table,
                                   teams_table=teams_table)

        assert predicted == ["round-13-panthers-v-broncos"]


@pytest.fixture
def weather_table(tables):
    """A `weather` table in the same already-active mock_aws context as `tables`."""
    client = boto3.client("dynamodb", region_name="ap-southeast-2")
    client.create_table(
        TableName="weather",
        KeySchema=[
            {"AttributeName": "pk", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    return boto3.resource("dynamodb", region_name="ap-southeast-2").Table("weather")


class TestPredictRoundWeatherSignal:
    """docs/plans/11-team-sheet-injury-weather-signals.md, Phase 4."""

    def test_bad_weather_is_reflected_in_key_factors(self, tables, weather_table):
        from v1.orchestrator.stats_predictor import predict_round

        predictions_table, results_table = tables
        # _matches()[0] is at "BlueBet Stadium", kick_off "2026-06-01T09:00:00Z".
        weather_table.put_item(Item={
            "pk": "weather#BlueBet Stadium", "sk": "2026-06-01",
            "rain_chance_pct": 90, "wind_kmh": 10,
        })

        predict_round(_matches()[:1], round_number=13, season=2026,
                       predictions_table=predictions_table, results_table=results_table,
                       weather_table=weather_table)

        item = predictions_table.scan()["Items"][0]
        assert any("variance widened" in f for f in item["key_factors"])

    def test_no_forecast_row_is_a_no_op(self, tables, weather_table):
        from v1.orchestrator.stats_predictor import predict_round

        predictions_table, results_table = tables
        predict_round(_matches()[:1], round_number=13, season=2026,
                       predictions_table=predictions_table, results_table=results_table,
                       weather_table=weather_table)

        item = predictions_table.scan()["Items"][0]
        assert not any("variance widened" in f for f in item["key_factors"])

    def test_omitting_weather_table_entirely_is_backward_compatible(self, tables):
        from v1.orchestrator.stats_predictor import predict_round

        predictions_table, results_table = tables
        predicted = predict_round(_matches()[:1], round_number=13, season=2026,
                                   predictions_table=predictions_table, results_table=results_table)

        assert predicted == ["round-13-panthers-v-broncos"]
