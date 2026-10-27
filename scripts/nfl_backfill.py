#!/usr/bin/env python3
"""Labelled NFL backfill CLI — thin wrapper over nfl/orchestrator/backfill.py.

Writes walk-forward predictions (``backfilled: true``) for the current season's
weeks before the first live week, never shadowing a live prediction and using
ratings strictly from earlier weeks. Season and weeks come from the data.

Usage (real AWS — run only after the NFL stack is deployed):
    AWS_DEFAULT_REGION=ap-southeast-2 NFL_PREDICTIONS_TABLE=nfl_predictions \\
        python3 scripts/nfl_backfill.py --dry-run
    AWS_DEFAULT_REGION=ap-southeast-2 NFL_PREDICTIONS_TABLE=nfl_predictions \\
        python3 scripts/nfl_backfill.py [--through-week N]

The CSV comes from NFL_GAMES_CSV_URL (default: the nflverse games.csv).
"""
from __future__ import annotations

import argparse
import os

import boto3

from common.nfl.games import parse_csv
from nfl.orchestrator import lambda_handler
from nfl.orchestrator.backfill import backfill


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Labelled NFL walk-forward backfill.")
    parser.add_argument("--through-week", type=int, default=None,
                        help="last week to backfill (capped below the live target week)")
    parser.add_argument("--dry-run", action="store_true", help="list, write nothing")
    args = parser.parse_args(argv)

    table = boto3.resource("dynamodb").Table(os.environ["NFL_PREDICTIONS_TABLE"])
    games, _ = parse_csv(lambda_handler.fetch_csv(lambda_handler.csv_url()))
    written = backfill(games, table, lambda_handler._now(),
                       through_week=args.through_week, dry_run=args.dry_run)
    verb = "would backfill (dry run)" if args.dry_run else "backfilled"
    print(f"{verb} {len(written)} game(s):")
    for match_id in written:
        print(f"  {match_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
