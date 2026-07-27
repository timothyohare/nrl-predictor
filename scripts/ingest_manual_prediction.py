"""Write a manually-obtained prediction — pasted from a Claude Pro chat
session using the prompt files scripts/gather_round_context.py produces —
into the real predictions table, in the exact shape v1/agent/lambda_handler.py
writes. This is what makes a free, manual prediction show up on the site
exactly like an automated one.

Usage:
    # Preview without writing
    AWS_DEFAULT_REGION=ap-southeast-2 python3 scripts/ingest_manual_prediction.py \\
        --match-id round-11-panthers-v-broncos --round 11 --file prediction.json --dry-run

    # Write for real
    AWS_DEFAULT_REGION=ap-southeast-2 python3 scripts/ingest_manual_prediction.py \\
        --match-id round-11-panthers-v-broncos --round 11 --file prediction.json

`--file` must contain the single JSON prediction object Claude returned,
matching v1/agent/prompt.py's documented output schema (predicted_winner,
predicted_margin, confidence, key_factors, reasoning, data_freshness, ...).
"""
import argparse
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import boto3

from v1.agent.prompt import PROMPT_VERSION
from v1.agent.schema import validate_prediction

REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "ap-southeast-2"

_DEFAULT_MODEL_USED = "manual-claude-pro"


def _extract_json_object(text: str) -> dict[str, Any]:
    """Find the prediction JSON object even when it's wrapped in a markdown
    code fence or has prose before/after — a copy-paste from a Claude Pro
    chat is at least as likely to include that as the automated agent's raw
    output (see v1/agent/graph.py's _extract_prediction_json, the same
    problem there)."""
    candidates = []
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence_match:
        candidates.append(fence_match.group(1))
    candidates.append(text.strip())
    if "{" in text and "}" in text:
        candidates.append(text[text.index("{"): text.rindex("}") + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("Could not find a JSON prediction object in the file")


def load_prediction(path: Path) -> dict[str, Any]:
    return _extract_json_object(path.read_text())


def next_generation(table, match_id: str) -> int:
    """Mirror v1/agent/lambda_handler.py's generation-counting logic exactly,
    so a manually-ingested prediction lands at the correct spot in the same
    generation sequence the automated pipeline uses."""
    existing = table.query(
        KeyConditionExpression="matchId = :m",
        FilterExpression="#s = :ok",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":m": match_id, ":ok": "OK"},
        Select="COUNT",
    )
    return existing.get("Count", 0) + 1


def build_prediction_row(
    raw: dict[str, Any], match_id: str, round_number: int, generated_at: str, generation: int,
) -> dict[str, Any]:
    """Validate and stamp a pasted prediction into the exact row shape the
    production agent Lambda writes (v1/agent/lambda_handler.py)."""
    prediction = validate_prediction(dict(raw))
    prediction.setdefault("model_used", _DEFAULT_MODEL_USED)
    prediction["matchId"] = match_id
    prediction["generatedAt"] = prediction.get("generated_at", generated_at)
    prediction["roundNumber"] = round_number
    prediction["staleness_flag"] = False
    prediction["status"] = "OK"
    prediction["prompt_version"] = PROMPT_VERSION
    prediction["generation"] = generation
    return prediction


def ingest_prediction_dict(
    table, raw: dict[str, Any], match_id: str, round_number: int, *, dry_run: bool = False,
) -> dict[str, Any]:
    """Validate and write a prediction that's already an in-memory dict — no
    file needed. The entry point for generating a prediction directly in a
    Claude Code session (covered by its Pro/Max subscription, not the
    production Lambda's metered API) instead of pasting into a separate
    Claude Pro chat and saving the response to a file."""
    generated_at = datetime.now(UTC).isoformat()
    generation = next_generation(table, match_id)
    row = build_prediction_row(raw, match_id, round_number, generated_at, generation)
    if not dry_run:
        table.put_item(Item=row)
    return row


def ingest_prediction(
    table, path: Path, match_id: str, round_number: int, *, dry_run: bool = False,
) -> dict[str, Any]:
    return ingest_prediction_dict(table, load_prediction(path), match_id, round_number, dry_run=dry_run)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--match-id", required=True)
    parser.add_argument("--round", type=int, required=True)
    parser.add_argument("--file", required=True, help="Path to the pasted prediction JSON")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print the row without writing")
    args = parser.parse_args()

    ddb = boto3.resource("dynamodb", region_name=REGION)
    table = ddb.Table(os.environ.get("PREDICTIONS_TABLE", "predictions"))

    row = ingest_prediction(table, Path(args.file), args.match_id, args.round, dry_run=args.dry_run)

    print(f"matchId: {row['matchId']}")
    print(f"generation: {row['generation']}")
    print(
        f"predicted_winner: {row.get('predicted_winner')} by {row.get('predicted_margin')} "
        f"({row.get('confidence')})"
    )
    if args.dry_run:
        print("\nDRY RUN — no write. Re-run without --dry-run to commit.")
    else:
        print(f"\nWrote prediction for {row['matchId']} to {table.name}.")


if __name__ == "__main__":
    main()
