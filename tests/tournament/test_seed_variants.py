"""Tests for tournament/seed_variants.py — specifically the `only` filter that lets
Phase 2 seed the new stats variant without re-seeding (and thus duplicating) the 8
existing production prompt variants. See docs/plans/10, Phase 2."""
import runpy
import sys

import boto3
import pytest
from moto import mock_aws

from v1.tournament import seed_variants as seed_variants_mod
from v1.tournament.seed_variants import _VARIANTS, seed

TABLE = "prompt_variants"


@pytest.fixture
def table():
    with mock_aws():
        client = boto3.client("dynamodb", region_name="ap-southeast-2")
        client.create_table(
            TableName=TABLE,
            KeySchema=[
                {"AttributeName": "variantId", "KeyType": "HASH"},
                {"AttributeName": "version", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "variantId", "AttributeType": "S"},
                {"AttributeName": "version", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        yield boto3.resource("dynamodb", region_name="ap-southeast-2").Table(TABLE)


def _scan_variant_ids(table) -> set[str]:
    return {item["variantId"] for item in table.scan()["Items"]}


class TestSeedOnlyFilter:
    def test_only_writes_the_requested_variant(self, table):
        seed(TABLE, variant_ids=["stats-elo-v1"])
        assert _scan_variant_ids(table) == {"stats-elo-v1"}

    def test_no_filter_writes_every_variant(self, table):
        seed(TABLE)
        assert _scan_variant_ids(table) == {v["variantId"] for v in _VARIANTS}

    def test_only_does_not_touch_other_variants_already_in_the_table(self, table):
        # Simulates the real scenario: 8 prompt variants already live in
        # production; seeding only the new stats variant must not write new
        # versions of the others (which would double-run them next round).
        table.put_item(Item={"variantId": "baseline", "version": "v0", "active": True})
        seed(TABLE, variant_ids=["stats-elo-v1"])

        baseline_versions = [
            item["version"] for item in table.scan()["Items"] if item["variantId"] == "baseline"
        ]
        assert baseline_versions == ["v0"]


class TestStatsVariantShape:
    def test_stats_variant_is_defined_with_correct_type(self):
        stats_variants = [v for v in _VARIANTS if v.get("variant_type") == "stats_model"]
        assert len(stats_variants) == 1
        assert stats_variants[0]["variantId"] == "stats-elo-v1"

    def test_seeded_item_carries_variant_type(self, table):
        seed(TABLE, variant_ids=["stats-elo-v1"])
        item = table.scan()["Items"][0]
        assert item["variant_type"] == "stats_model"

    def test_prompt_variants_default_to_prompt_type(self, table):
        seed(TABLE, variant_ids=["baseline"])
        item = table.scan()["Items"][0]
        assert item["variant_type"] == "prompt"


class TestSeedEdgeCases:
    def test_unknown_variant_id_raises_value_error(self, table):
        with pytest.raises(ValueError, match="Unknown variantId"):
            seed(TABLE, variant_ids=["no-such-variant"])

    def test_dry_run_writes_nothing_but_reports_intent(self, table, capsys):
        seed(TABLE, dry_run=True, variant_ids=["stats-elo-v1"])

        assert table.scan()["Items"] == []
        out = capsys.readouterr().out
        assert "[dry-run]" in out
        assert "stats-elo-v1" in out


class TestSeedCli:
    def test_main_entrypoint_honours_dry_run_and_only(self, table, monkeypatch, capsys):
        monkeypatch.setattr(
            sys, "argv",
            ["seed_variants", "--dry-run", "--table", TABLE, "--only", "stats-elo-v1"],
        )

        runpy.run_path(seed_variants_mod.__file__, run_name="__main__")

        out = capsys.readouterr().out
        assert "[dry-run]" in out
        assert "stats-elo-v1" in out
        assert table.scan()["Items"] == []
