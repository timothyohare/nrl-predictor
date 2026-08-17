"""Tests for the stats-model tournament variant (no LLM calls). See docs/plans/10, Phase 2."""
import boto3
import pytest
from moto import mock_aws

from v1.tournament.stats_variant_runner import run_stats_variant_for_round

VARIANT_ID = "stats-elo-v1"
RESULTS_TABLE = "results"
SIM_TABLE = "simulation_predictions"


@pytest.fixture
def tables():
    with mock_aws():
        client = boto3.client("dynamodb", region_name="ap-southeast-2")
        client.create_table(
            TableName=RESULTS_TABLE,
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
        client.create_table(
            TableName=SIM_TABLE,
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "generatedAt", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "generatedAt", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        ddb = boto3.resource("dynamodb", region_name="ap-southeast-2")
        yield ddb.Table(RESULTS_TABLE), ddb.Table(SIM_TABLE)


def _put_result(table, match_id, home, away, home_score, away_score):
    table.put_item(Item={
        "matchId": match_id,
        "scoredAt": "2026-06-01T00:00:00Z",
        "homeTeam": home,
        "awayTeam": away,
        "homeScore": home_score,
        "awayScore": away_score,
        "winner": home if home_score > away_score else away,
        "margin": abs(home_score - away_score),
        "matchState": "FullTime",
    })


class TestRunStatsVariantForRound:
    def test_writes_one_prediction_per_match(self, tables):
        results_table, sim_table = tables
        match_ids = ["round-13-panthers-v-broncos", "round-13-storm-v-roosters"]

        records = run_stats_variant_for_round(
            variant_id=VARIANT_ID,
            match_ids=match_ids,
            round_number=13,
            season=2026,
            sim_table=sim_table,
            results_table=results_table,
        )

        assert [r["matchId"] for r in records] == match_ids
        for r in records:
            assert r["variantId"] == VARIANT_ID
            assert r["pk"] == f"{r['matchId']}#{VARIANT_ID}"
            assert r["roundNumber"] == 13
            assert r["season"] == 2026
            assert r["confidence"] in ("HIGH", "MEDIUM", "LOW")
            assert isinstance(r["predicted_margin"], int)
            assert "generatedAt" in r
            assert "reasoning" in r

    def test_predicted_winner_is_one_of_the_two_teams(self, tables):
        results_table, sim_table = tables
        records = run_stats_variant_for_round(
            variant_id=VARIANT_ID,
            match_ids=["round-13-panthers-v-broncos"],
            round_number=13,
            season=2026,
            sim_table=sim_table,
            results_table=results_table,
        )
        assert records[0]["predicted_winner"] in ("panthers", "broncos")

    def test_uses_prior_round_history_no_look_ahead(self, tables):
        results_table, sim_table = tables
        # Panthers thrash Broncos in round 12 — should raise Panthers' rating for round 13.
        _put_result(results_table, "round-12-panthers-v-broncos", "panthers", "broncos", 50, 0)

        records = run_stats_variant_for_round(
            variant_id=VARIANT_ID,
            match_ids=["round-13-panthers-v-storm"],
            round_number=13,
            season=2026,
            sim_table=sim_table,
            results_table=results_table,
        )
        # Panthers should now be favoured against a team they've never played,
        # purely from their round-12 rating gain being visible for round 13.
        assert records[0]["predicted_winner"] == "panthers"

    def test_writes_to_sim_table(self, tables):
        results_table, sim_table = tables
        records = run_stats_variant_for_round(
            variant_id=VARIANT_ID,
            match_ids=["round-13-panthers-v-broncos"],
            round_number=13,
            season=2026,
            sim_table=sim_table,
            results_table=results_table,
        )
        resp = sim_table.get_item(
            Key={"pk": records[0]["pk"], "generatedAt": records[0]["generatedAt"]}
        )
        assert "Item" in resp
        assert resp["Item"]["predicted_winner"] == records[0]["predicted_winner"]

    def test_skips_unparseable_match_id(self, tables):
        results_table, sim_table = tables
        records = run_stats_variant_for_round(
            variant_id=VARIANT_ID,
            match_ids=["not-a-real-matchid", "round-13-panthers-v-broncos"],
            round_number=13,
            season=2026,
            sim_table=sim_table,
            results_table=results_table,
        )
        assert [r["matchId"] for r in records] == ["round-13-panthers-v-broncos"]

    def test_deterministic_given_same_inputs(self, tables):
        results_table, sim_table = tables
        first = run_stats_variant_for_round(
            variant_id=VARIANT_ID,
            match_ids=["round-13-panthers-v-broncos"],
            round_number=13,
            season=2026,
            results_table=results_table,
        )
        second = run_stats_variant_for_round(
            variant_id=VARIANT_ID,
            match_ids=["round-13-panthers-v-broncos"],
            round_number=13,
            season=2026,
            results_table=results_table,
        )
        assert first[0]["predicted_winner"] == second[0]["predicted_winner"]
        assert first[0]["predicted_margin"] == second[0]["predicted_margin"]
        assert first[0]["confidence"] == second[0]["confidence"]

    def test_no_llm_import_at_call_time(self, tables):
        # Sanity guard for the whole point of this variant: it must not touch
        # the agent/Claude at all. If this module ever imports v1.agent.graph,
        # that's a regression against the "Anthropic-independent" design goal.
        import v1.tournament.stats_variant_runner as mod
        assert "run_agent" not in dir(mod)
