"""Tests for tournament/pause_claude_variants.py — the operational script that
pauses the 7 Claude prompt tournament variants in the live prompt_variants table
while leaving stats-elo-v1 running.

The orchestrator selects variants with a plain scan over EVERY row where
`active=True` (all versions of all variantIds — no latest-version collapse), so
these tests assert the pause touches every version row of each Claude variant and
never touches stats-elo-v1.
"""
import sys

import boto3
import pytest
from moto import mock_aws

from v1.tournament.pause_claude_variants import (
    KEEP_ACTIVE,
    claude_variant_ids,
    main,
    run,
    set_active,
)
from v1.tournament.seed_variants import _VARIANTS

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
        tbl = boto3.resource("dynamodb", region_name="ap-southeast-2").Table(TABLE)
        yield tbl


def _seed_live_table(tbl, *, claude_versions=("v1", "v2"), stats_versions=("v1",)):
    """Mirror the real table: multiple active versions per Claude variantId
    (seed_variants writes a new version every run and never deletes old ones),
    plus stats-elo-v1."""
    for vid in claude_variant_ids():
        for ver in claude_versions:
            tbl.put_item(Item={"variantId": vid, "version": ver, "active": True,
                               "variant_type": "prompt"})
    for ver in stats_versions:
        tbl.put_item(Item={"variantId": KEEP_ACTIVE, "version": ver, "active": True,
                           "variant_type": "stats_model"})


def _rows(tbl):
    return tbl.scan()["Items"]


def _active_map(tbl):
    return {(r["variantId"], r["version"]): bool(r["active"]) for r in _rows(tbl)}


# --- claude_variant_ids -------------------------------------------------------

def test_claude_variant_ids_excludes_stats_elo():
    ids = claude_variant_ids()
    assert KEEP_ACTIVE not in ids
    assert "baseline" in ids
    assert set(ids) == {
        v["variantId"] for v in _VARIANTS if v.get("variant_type", "prompt") != "stats_model"
    }
    # every id is a real prompt variant, and there is at least one
    assert len(ids) >= 1


# --- pause (default) --------------------------------------------------------

def test_pause_deactivates_every_version_of_every_claude_variant(table):
    _seed_live_table(table, claude_versions=("v1", "v2", "v3"))
    run(TABLE)

    amap = _active_map(table)
    for vid in claude_variant_ids():
        for ver in ("v1", "v2", "v3"):
            assert amap[(vid, ver)] is False, f"{vid}@{ver} should be paused"


def test_pause_leaves_stats_elo_v1_active(table):
    _seed_live_table(table, stats_versions=("v1", "v2"))
    run(TABLE)

    amap = _active_map(table)
    assert amap[(KEEP_ACTIVE, "v1")] is True
    assert amap[(KEEP_ACTIVE, "v2")] is True


def test_pause_is_idempotent(table):
    _seed_live_table(table)
    first = run(TABLE)
    assert first, "first run should change rows"
    second = run(TABLE)
    assert second == [], "second run should be a no-op"


def test_pause_only_writes_rows_that_need_changing(table):
    _seed_live_table(table)
    # one Claude row already paused
    target = claude_variant_ids()[0]
    table.update_item(
        Key={"variantId": target, "version": "v1"},
        UpdateExpression="SET active = :f",
        ExpressionAttributeValues={":f": False},
    )
    changed = run(TABLE)
    assert (target, "v1") not in changed
    assert (target, "v2") in changed


# --- dry-run -------------------------------------------------------------------

def test_dry_run_writes_nothing_but_reports(table, capsys):
    _seed_live_table(table)
    changed = run(TABLE, dry_run=True)

    assert changed, "dry-run still reports which rows it would change"
    # nothing actually changed
    assert all(v is True for v in _active_map(table).values())
    out = capsys.readouterr().out
    assert "[dry-run]" in out


# --- reactivate -------------------------------------------------------------

def test_reactivate_restores_all_claude_variants(table):
    _seed_live_table(table)
    run(TABLE)  # pause
    run(TABLE, reactivate=True)  # reverse

    amap = _active_map(table)
    for vid in claude_variant_ids():
        for ver in ("v1", "v2"):
            assert amap[(vid, ver)] is True


def test_reactivate_does_not_touch_stats_elo(table):
    _seed_live_table(table)
    run(TABLE)
    run(TABLE, reactivate=True)
    assert _active_map(table)[(KEEP_ACTIVE, "v1")] is True


# --- set_active unit --------------------------------------------------------

def test_set_active_ignores_untargeted_variant_ids(table):
    table.put_item(Item={"variantId": "some-other-variant", "version": "v1", "active": True})
    table.put_item(Item={"variantId": "baseline", "version": "v1", "active": True})
    changed = set_active(table, ["baseline"], active=False)
    assert changed == [("baseline", "v1")]
    assert _active_map(table)[("some-other-variant", "v1")] is True


def test_set_active_treats_missing_active_key_as_true(table):
    table.put_item(Item={"variantId": "baseline", "version": "v1"})  # no active key
    changed = set_active(table, ["baseline"], active=False)
    assert changed == [("baseline", "v1")]
    assert _active_map(table)[("baseline", "v1")] is False


# --- CLI entrypoint --------------------------------------------------------

def test_main_dry_run_via_argv(table, monkeypatch, capsys):
    _seed_live_table(table)
    monkeypatch.setattr(sys, "argv", ["pause_claude_variants", "--table", TABLE, "--dry-run"])
    main()
    assert all(v is True for v in _active_map(table).values())
    assert "[dry-run]" in capsys.readouterr().out


def test_main_applies_pause_via_argv(table, monkeypatch):
    _seed_live_table(table)
    monkeypatch.setattr(sys, "argv", ["pause_claude_variants", "--table", TABLE])
    main()
    amap = _active_map(table)
    assert all(amap[(vid, ver)] is False for vid in claude_variant_ids() for ver in ("v1", "v2"))
    assert amap[(KEEP_ACTIVE, "v1")] is True


def test_main_reactivate_via_argv(table, monkeypatch):
    _seed_live_table(table)
    run(TABLE)
    monkeypatch.setattr(sys, "argv", ["pause_claude_variants", "--table", TABLE, "--reactivate"])
    main()
    assert all(v is True for v in _active_map(table).values())


def test_main_defaults_table_from_env(table, monkeypatch):
    _seed_live_table(table)
    monkeypatch.setenv("PROMPT_VARIANTS_TABLE", TABLE)
    monkeypatch.setattr(sys, "argv", ["pause_claude_variants", "--dry-run"])
    main()  # should not raise — resolves table name from env
