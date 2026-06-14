"""Create the DynamoDB tables the API read path joins, then seed a realistic
round so the acceptance check has something to assert against.

Run by gate-verify's `setup` step against DynamoDB Local (see
.claude/harness.json). Points at the local mock via AWS_ENDPOINT_URL_DYNAMODB.
Idempotent: drops-and-recreates each table so reruns start clean.
"""
import os
import time
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError

REGION = os.environ.get("AWS_DEFAULT_REGION", "ap-southeast-2")

# (table env var, partition key, sort key)
TABLES = [
    ("PREDICTIONS_TABLE", "matchId", "generatedAt"),
    ("RESULTS_TABLE", "matchId", "scoredAt"),
    ("RETROSPECTIVES_TABLE", "matchId", "generatedAt"),
    ("ODDS_TABLE", "matchId", "scrapedAt"),
    ("RATE_LIMITS_TABLE", "pk", None),
]


def _client():
    return boto3.client("dynamodb", region_name=REGION)


def _resource():
    return boto3.resource("dynamodb", region_name=REGION)


def create_tables() -> None:
    client = _client()
    for env_var, pk, sk in TABLES:
        name = os.environ[env_var]
        try:
            client.delete_table(TableName=name)
            client.get_waiter("table_not_exists").wait(TableName=name)
        except ClientError:
            pass  # didn't exist yet

        key_schema = [{"AttributeName": pk, "KeyType": "HASH"}]
        attrs = [{"AttributeName": pk, "AttributeType": "S"}]
        if sk:
            key_schema.append({"AttributeName": sk, "KeyType": "RANGE"})
            attrs.append({"AttributeName": sk, "AttributeType": "S"})

        client.create_table(
            TableName=name,
            KeySchema=key_schema,
            AttributeDefinitions=attrs,
            BillingMode="PAY_PER_REQUEST",
        )
        client.get_waiter("table_exists").wait(TableName=name)
        print(f"  created {name}")


def seed() -> None:
    ddb = _resource()
    preds = ddb.Table(os.environ["PREDICTIONS_TABLE"])
    results = ddb.Table(os.environ["RESULTS_TABLE"])
    retros = ddb.Table(os.environ["RETROSPECTIVES_TABLE"])
    odds = ddb.Table(os.environ["ODDS_TABLE"])

    # Match A — played, scored, retrospective written, agrees with the market.
    preds.put_item(Item={
        "matchId": "round-12-panthers-v-broncos",
        "generatedAt": "2026-05-15T20:00:00Z",
        "roundNumber": 12,
        "season": 2026,
        "predicted_winner": "Panthers",
        "predicted_margin": 10,
        "confidence": "HIGH",
        "key_factors": ["Forward pack dominance", "Home advantage"],
        "reasoning": "x" * 220,
        "status": "OK",
        "staleness_flag": False,
        "generation": 1,
    })
    # An earlier, superseded generation for the same match — the API must keep
    # only the most recent generatedAt.
    preds.put_item(Item={
        "matchId": "round-12-panthers-v-broncos",
        "generatedAt": "2026-05-13T16:00:00Z",
        "roundNumber": 12,
        "season": 2026,
        "predicted_winner": "Broncos",
        "predicted_margin": 4,
        "confidence": "LOW",
        "key_factors": ["Early team list"],
        "reasoning": "y" * 220,
        "status": "OK",
        "staleness_flag": False,
        "generation": 0,
    })
    results.put_item(Item={
        "matchId": "round-12-panthers-v-broncos",
        "scoredAt": "2026-05-17T22:00:00Z",
        "roundNumber": 12,
        "winner": "Panthers",
        "homeTeam": "Panthers",
        "awayTeam": "Broncos",
        "homeScore": 28,
        "awayScore": 18,
        "margin": 10,
    })
    retros.put_item(Item={
        "matchId": "round-12-panthers-v-broncos",
        "generatedAt": "2026-05-17T22:05:00Z",
        "roundNumber": 12,
        "verdict": "Correct call — Panthers controlled the game as predicted.",
        "hit_factors": ["Forward pack dominance"],
        "missed_factors": [],
        "what_actually_happened": "Penrith led from early and never relinquished control.",
        "lesson": "Home forward dominance remains a strong signal.",
    })
    odds.put_item(Item={
        "matchId": "round-12-panthers-v-broncos",
        "scrapedAt": "2026-05-15T08:00:00Z",
        "roundNumber": 12,
        "market_favourite": "Panthers",
        "market_margin": Decimal("8"),
        "home_odds": Decimal("1.5"),
        "away_odds": Decimal("2.6"),
        "implied_home_prob": Decimal("0.66"),
        "implied_away_prob": Decimal("0.38"),
    })

    # Match B — not yet played (no result, no retrospective). Prediction
    # disagrees with the market on the winner, so the API must flag is_outlier.
    preds.put_item(Item={
        "matchId": "round-12-storm-v-eels",
        "generatedAt": "2026-05-15T20:00:00Z",
        "roundNumber": 12,
        "season": 2026,
        "predicted_winner": "Eels",
        "predicted_margin": 6,
        "confidence": "MEDIUM",
        "key_factors": ["Eels spine in form"],
        "reasoning": "z" * 220,
        "status": "OK",
        "staleness_flag": False,
        "generation": 1,
    })
    odds.put_item(Item={
        "matchId": "round-12-storm-v-eels",
        "scrapedAt": "2026-05-15T08:00:00Z",
        "roundNumber": 12,
        "market_favourite": "Storm",
        "market_margin": Decimal("12"),
        "home_odds": Decimal("1.3"),
        "away_odds": Decimal("3.4"),
        "implied_home_prob": Decimal("0.74"),
        "implied_away_prob": Decimal("0.29"),
    })

    # A FAILED row that must never surface in the API response.
    preds.put_item(Item={
        "matchId": "round-12-sharks-v-titans",
        "generatedAt": "2026-05-15T20:00:00Z",
        "roundNumber": 12,
        "season": 2026,
        "status": "FAILED",
        "error": "Agent produced non-JSON output",
    })

    print("  seeded round 12 (2 OK matches + 1 FAILED, results/retro/odds joins)")


def main() -> None:
    print("local_setup: creating tables ...")
    create_tables()
    # Tiny settle so PAY_PER_REQUEST tables are fully active before writes.
    time.sleep(0.5)
    print("local_setup: seeding ...")
    seed()
    print("local_setup: done")


if __name__ == "__main__":
    main()
