"""Pause (or reactivate) the Claude/prompt tournament variants in the LIVE
``prompt_variants`` DynamoDB table.

Why this exists
---------------
``stats-elo-v1`` (the local Elo + Monte Carlo model, no Claude call) beat all 7
Claude prompt variants 8/8 during the 2026-08 Anthropic credit outage and is now
the production predictor. The orchestrator's automatic per-round path no longer
calls the Claude agent at all, so the prompt tournament is spending money tuning a
prompt for a code path that never runs unattended. Pause the Claude variants; keep
the tournament harness and ``stats-elo-v1`` running so the comparison stays alive.

This must be a config flip, not a deletion — fully reversible with ``--reactivate``.

How the orchestrator selects variants (why this updates EVERY version row)
------------------------------------------------------------------------
``tournament/orchestrator_lambda.py`` does a plain
``variants_table.scan(FilterExpression="#a = :t", ... ":t": True)`` — it launches a
worker for **every row** where ``active`` is truthy, across **all versions** of
every ``variantId`` (no "latest version per variantId" collapse). ``seed_variants``
writes a new ``version`` (ISO-timestamp sort key) row on each run and never deletes
old ones. So to genuinely stop the Claude variants next round, ``active`` must be
set ``False`` on *every existing version row* of each Claude ``variantId`` — not
just the newest. That is exactly what this script does (``scan_all`` +
per-``(variantId, version)`` ``update_item``).

The companion change in ``seed_variants._VARIANTS`` (each Claude variant carries
``"active": False``) stops a future re-seed from writing a fresh ``active=True``
row and silently un-pausing them. Both pieces are needed.

``stats-elo-v1`` is never in the target set — it is untouched by both ``--pause``
(default) and ``--reactivate``.

Usage
-----
Dry-run first (shows every row it would change, writes nothing)::

    AWS_DEFAULT_REGION=ap-southeast-2 python3 -m v1.tournament.pause_claude_variants --dry-run

Apply the pause (the operational action)::

    AWS_DEFAULT_REGION=ap-southeast-2 python3 -m v1.tournament.pause_claude_variants

Reverse it (reactivate all Claude variants — e.g. Anthropic credit is healthy and
you want the prompt tournament back)::

    AWS_DEFAULT_REGION=ap-southeast-2 python3 -m v1.tournament.pause_claude_variants --reactivate

Override the table name with ``--table`` (defaults to ``$PROMPT_VARIANTS_TABLE``
or ``prompt_variants``).
"""
import argparse
import os

import boto3

from common.dynamo import scan_all
from v1.tournament.seed_variants import _VARIANTS

# The one variant that must keep running — local model, immune to Anthropic outages.
KEEP_ACTIVE = "stats-elo-v1"


def claude_variant_ids() -> list[str]:
    """Every non-``stats_model`` variantId defined in ``seed_variants._VARIANTS``.

    Derived from the source of truth so it stays correct if a prompt variant is
    added or renamed. ``stats-elo-v1`` (``variant_type == "stats_model"``) is
    excluded by construction.
    """
    ids = [
        str(v["variantId"])
        for v in _VARIANTS
        if v.get("variant_type", "prompt") != "stats_model"
    ]
    assert KEEP_ACTIVE not in ids, f"{KEEP_ACTIVE} must never be in the pause set"
    return ids


def set_active(
    table,
    variant_ids: list[str],
    *,
    active: bool,
    dry_run: bool = False,
) -> list[tuple[str, str]]:
    """Set ``active=<active>`` on every version row of each id in ``variant_ids``.

    Scans the whole table (following pagination), and for each row whose
    ``variantId`` is targeted and whose current ``active`` differs from the
    target, issues a single ``update_item`` on that ``(variantId, version)`` key.
    Returns the list of ``(variantId, version)`` pairs that were (or, under
    ``dry_run``, would be) changed.
    """
    targets = set(variant_ids)
    changed: list[tuple[str, str]] = []

    for item in scan_all(table):
        if item["variantId"] not in targets:
            continue
        if bool(item.get("active", True)) == active:
            continue  # already in the desired state — no write
        key = (item["variantId"], item["version"])
        changed.append(key)
        if dry_run:
            print(f"  [dry-run] would set active={active}: {key[0]} @ {key[1]}")
        else:
            table.update_item(
                Key={"variantId": key[0], "version": key[1]},
                UpdateExpression="SET #a = :v",
                ExpressionAttributeNames={"#a": "active"},
                ExpressionAttributeValues={":v": active},
            )
            print(f"  set active={active}: {key[0]} @ {key[1]}")

    return changed


def run(table_name: str, *, reactivate: bool = False, dry_run: bool = False) -> list[tuple[str, str]]:
    target_active = reactivate  # --reactivate -> True; default (pause) -> False
    verb = "Reactivating" if reactivate else "Pausing"
    ids = claude_variant_ids()
    print(f"{verb} {len(ids)} Claude variant(s) in {table_name} "
          f"(target active={target_active}); {KEEP_ACTIVE} left untouched.")
    print(f"  variantIds: {ids}")

    table = boto3.resource("dynamodb").Table(table_name)
    changed = set_active(table, ids, active=target_active, dry_run=dry_run)

    if not changed:
        print("No rows needed changing (already in the target state).")
    else:
        print(f"{'Would change' if dry_run else 'Changed'} {len(changed)} row(s).")
    return changed


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Pause/reactivate the Claude prompt tournament variants in the live table."
    )
    parser.add_argument(
        "--table",
        default=os.environ.get("PROMPT_VARIANTS_TABLE", "prompt_variants"),
        help="prompt_variants table name (default: $PROMPT_VARIANTS_TABLE or 'prompt_variants')",
    )
    parser.add_argument(
        "--reactivate",
        action="store_true",
        help="inverse: set the Claude variants back to active=True",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="show every row that would change; write nothing",
    )
    args = parser.parse_args(argv)
    run(args.table, reactivate=args.reactivate, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
