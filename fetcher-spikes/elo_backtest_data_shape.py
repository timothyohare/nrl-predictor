"""Spike: confirm the `results` table's shape for the Elo backtest (docs/plans/10).

Answers: does every row have a usable round number, how many canonical
matches (deduped by matchId) exist, and what round range they span — before
writing tests/scripts against assumptions about this data.

Run: AWS_DEFAULT_REGION=ap-southeast-2 python3 fetcher-spikes/elo_backtest_data_shape.py
"""
from __future__ import annotations

import boto3

from common.dynamo import scan_all
from common.match_id import round_of

RESULTS_TABLE = "results"


def canonical_results(table) -> list[dict]:
    """One row per matchId: the row with the latest scoredAt (corrections overwrite)."""
    rows = scan_all(table)
    latest: dict[str, dict] = {}
    for row in rows:
        match_id = row["matchId"]
        if match_id not in latest or row["scoredAt"] > latest[match_id]["scoredAt"]:
            latest[match_id] = row
    return list(latest.values())


def main() -> None:
    table = boto3.resource("dynamodb").Table(RESULTS_TABLE)
    rows = canonical_results(table)

    missing_round_number = [r["matchId"] for r in rows if "roundNumber" not in r]
    round_of_mismatches = [
        r["matchId"]
        for r in rows
        if "roundNumber" in r and int(r["roundNumber"]) != round_of(r["matchId"])
    ]
    rounds = sorted({round_of(r["matchId"]) for r in rows if round_of(r["matchId"]) is not None})

    print(f"canonical matches: {len(rows)} (raw rows scanned: pre-dedupe count not tracked)")
    print(f"round range: {rounds[0]}-{rounds[-1]}" if rounds else "round range: (none)")
    print(f"rounds present: {rounds}")
    print(f"rows missing roundNumber field: {len(missing_round_number)} {missing_round_number[:5]}")
    print(f"roundNumber field disagrees with match_id round_of(): {len(round_of_mismatches)} {round_of_mismatches[:5]}")

    missing_scores = [
        r["matchId"] for r in rows if "homeScore" not in r or "awayScore" not in r
    ]
    print(f"rows missing homeScore/awayScore: {len(missing_scores)} {missing_scores[:5]}")

    non_fulltime = [r["matchId"] for r in rows if r.get("matchState") != "FullTime"]
    print(f"rows with matchState != FullTime: {len(non_fulltime)} {non_fulltime[:5]}")


if __name__ == "__main__":
    main()
