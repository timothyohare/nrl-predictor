#!/usr/bin/env python3
"""One-off backfill: re-key team-sheet rows in the `teams` table by the
round-qualified slug the agent queries with.

Background — until the 2026-06-14 fix (commit "key team sheets by slug so the
agent can actually read them"), the team_sheet scraper and orchestrator wrote
team-sheet rows under the *numerical* NRL matchId embedded in the q-data
(e.g. "20261111240") instead of the slug ("round-12-sea-eagles-v-titans").
The agent's get_team_sheet / spine_synergy tools look up by slug, so those rows
were never read. They are still picked up by spine_synergy's *historical* scan
(which scans by homeTeam/awayTeam, not the key), but:

  1. round 15 now has BOTH a numeric row and a slug row → double-counted in
     spine synergy history.
  2. spine_synergy resolves each historical game's win/loss via
     `_get_result_for_match(sheet["teamId"])`; a numeric teamId never matches a
     result row (results are keyed by slug), so win rates are wrong.

This script re-keys every numeric-keyed team-sheet row to its slug:
  - derive the slug from the draw rows (matchId, round, team) by matching
    (round, homeTeam, awayTeam);
  - if a slug row already exists for that round, just delete the numeric
    duplicate (keep the newer slug row);
  - otherwise copy the row under the slug key, then delete the numeric row.

Dry-run by default. Pass --apply to actually write/delete.

    AWS_DEFAULT_REGION=ap-southeast-2 python3 scripts/backfill_team_sheet_keys.py
    AWS_DEFAULT_REGION=ap-southeast-2 python3 scripts/backfill_team_sheet_keys.py --apply
"""
import argparse
import os

import boto3

TEAMS_TABLE = os.environ.get("TEAMS_TABLE", "teams")


def _is_numeric_key(team_id: str) -> bool:
    return team_id.isdigit()


def build_slug_map(table) -> dict[tuple[str, str, str], str]:
    """Map (round, homeTeam, awayTeam) -> slug matchId from the draw rows.

    Draw rows are keyed ``{slug}#home`` / ``{slug}#away`` and carry
    ``matchId`` (= slug), ``round`` and ``team``."""
    sides: dict[str, dict] = {}
    resp = table.scan(
        FilterExpression="attribute_exists(matchId) AND attribute_exists(team)",
        ProjectionExpression="teamId, matchId, #r, team",
        ExpressionAttributeNames={"#r": "round"},
    )
    items = resp.get("Items", [])
    while "LastEvaluatedKey" in resp:
        resp = table.scan(
            FilterExpression="attribute_exists(matchId) AND attribute_exists(team)",
            ProjectionExpression="teamId, matchId, #r, team",
            ExpressionAttributeNames={"#r": "round"},
            ExclusiveStartKey=resp["LastEvaluatedKey"],
        )
        items += resp.get("Items", [])

    for it in items:
        tid = it["teamId"]
        if "#" not in tid:
            continue
        slug, side = tid.rsplit("#", 1)
        rec = sides.setdefault(slug, {"round": it.get("round", "")})
        rec[side] = it["team"]

    slug_map: dict[tuple[str, str, str], str] = {}
    for slug, rec in sides.items():
        if "home" in rec and "away" in rec:
            slug_map[(rec["round"], rec["home"], rec["away"])] = slug
    return slug_map


def fetch_team_sheet_rows(table) -> list[dict]:
    resp = table.scan(FilterExpression="attribute_exists(homePlayers)")
    items = resp.get("Items", [])
    while "LastEvaluatedKey" in resp:
        resp = table.scan(
            FilterExpression="attribute_exists(homePlayers)",
            ExclusiveStartKey=resp["LastEvaluatedKey"],
        )
        items += resp.get("Items", [])
    return items


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="actually write/delete (default: dry-run)")
    args = ap.parse_args()

    table = boto3.resource("dynamodb").Table(TEAMS_TABLE)
    slug_map = build_slug_map(table)
    rows = fetch_team_sheet_rows(table)

    existing_slug_rows = {
        (r["teamId"], r.get("round", "")) for r in rows if not _is_numeric_key(r["teamId"])
    }

    rekeyed = deduped = skipped = 0
    for row in rows:
        tid = row["teamId"]
        if not _is_numeric_key(tid):
            continue
        rnd = row.get("round", "")
        key = (rnd, row.get("homeTeam", ""), row.get("awayTeam", ""))
        slug = slug_map.get(key)
        if not slug:
            print(f"  SKIP  {tid} r={rnd} {row.get('homeTeam')} v {row.get('awayTeam')} — no draw row to derive slug")
            skipped += 1
            continue

        if (slug, rnd) in existing_slug_rows:
            print(f"  DEDUP {tid} -> delete (slug row {slug} r={rnd} already exists)")
            deduped += 1
            if args.apply:
                table.delete_item(Key={"teamId": tid, "round": rnd})
        else:
            print(f"  REKEY {tid} -> {slug} (r={rnd})")
            rekeyed += 1
            if args.apply:
                new_item = dict(row)
                new_item["teamId"] = slug
                table.put_item(Item=new_item)
                table.delete_item(Key={"teamId": tid, "round": rnd})
                existing_slug_rows.add((slug, rnd))

    mode = "APPLIED" if args.apply else "DRY-RUN (pass --apply to write)"
    print(f"\n{mode}: {rekeyed} re-keyed, {deduped} duplicates deleted, {skipped} skipped")


if __name__ == "__main__":
    main()
