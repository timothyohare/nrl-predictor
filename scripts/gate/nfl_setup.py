"""Third-stage seed for gate-verify: the NFL tables (spec Phase 3, criterion 3.10).

Creates `nfl_games` (PK matchId) and `nfl_predictions` (PK matchId, SK
generatedAt) in DynamoDB Local, mirroring infra/nfl_stack.py. The write-path data
is not seeded here: the orchestrator ingests tests/fixtures/nfl_games_sample.csv
over file:// in the BDD steps, exactly as it would fetch the nflverse CSV live.

`seed_api()` loads the small, hand-built 2026 week-8 read-path set the NFL API
scenarios assert against (spec Phase 4, criterion 4.9): one superseded generation
and one FAILED row that must never surface, a played and an unplayed game, an
outlier and a non-outlier, a game with no market, and an orphan prediction whose
game is no longer in nfl_games. nfl_api.feature reseeds it in its Background, so
it never depends on scenario order.

Run after `write_path_setup.py` (see the `setup` key in .claude/harness.json).
Owns only these two tables, so the NRL read/write-path tables are untouched.
Idempotent: drop-and-recreates both tables so reruns start clean.
"""
import os
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError

REGION = os.environ.get("AWS_DEFAULT_REGION", "ap-southeast-2")

# (table env var, partition key, sort key)
TABLES = [
    ("NFL_GAMES_TABLE", "matchId", None),
    ("NFL_PREDICTIONS_TABLE", "matchId", "generatedAt"),
]


def create_tables() -> None:
    client = boto3.client("dynamodb", region_name=REGION)
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


GB = "nfl-2026-week-8-packers-v-panthers"    # played, market agrees -> not an outlier
DEN = "nfl-2026-week-8-broncos-v-chiefs"     # unplayed, market favours Chiefs -> outlier
NYJ = "nfl-2026-week-8-jets-v-raiders"       # unplayed, no market -> no outlier field
ORPHAN = "nfl-2026-week-8-bills-v-dolphins"  # prediction only: rescheduled away

_SCRAPED = "2026-10-28T12:00:00+00:00"


def _game(match_id: str, home: str, away: str, kickoff: str, *,
          score: tuple[int, int] | None = None, market: dict | None = None) -> dict:
    item: dict = {
        "matchId": match_id, "game_id": match_id, "season": 2026, "week": 8, "stage": "REG",
        "home_team": home, "away_team": away, "neutral": False, "played": score is not None,
        "kickoff_utc": kickoff, "scraped_at": _SCRAPED,
    }
    if score is not None:
        item["home_score"], item["away_score"] = score
    if market is not None:
        item["market"] = market
    return item


def _prediction(match_id: str, generated_at: str, *, winner: str = "", margin: int = 0,
                p_home: str = "0.5", status: str = "OK", generation: int = 1) -> dict:
    row: dict = {
        "matchId": match_id, "generatedAt": generated_at, "season": 2026, "week": 8,
        "model_used": "nfl-elo-v1", "generation": generation, "backfilled": False,
        "scraped_at": generated_at, "status": status,
    }
    if status != "OK":
        return {**row, "error": "forced failure"}
    return {
        **row, "stage": "REG", "predicted_winner": winner, "predicted_margin": margin,
        "margin_low": max(margin - 5, 0), "margin_high": margin + 5,
        "home_win_probability": Decimal(p_home), "confidence": "MEDIUM",
        "key_factors": ["Elo rating gap"], "reasoning": "Seeded for the gate.",
        "neutral": False, "kickoff_utc": "2026-11-01T18:00:00Z",
    }


GAMES = [
    _game(GB, "packers", "panthers", "2026-10-30T00:15:00Z", score=(24, 17),
          market={"spread_line": Decimal("3.5"), "home_moneyline": -198, "away_moneyline": 164}),
    _game(DEN, "broncos", "chiefs", "2026-11-01T21:25:00Z",
          market={"spread_line": Decimal("-1.5"), "home_moneyline": 105, "away_moneyline": -125}),
    _game(NYJ, "jets", "raiders", "2026-11-01T18:00:00Z"),
]

PREDICTIONS = [
    _prediction(GB, "2026-10-27T12:00:00+00:00", winner="panthers", margin=3, p_home="0.45"),
    _prediction(GB, "2026-10-28T12:00:00+00:00", winner="packers", margin=4, p_home="0.62",
                generation=2),
    _prediction(GB, "2026-10-29T12:00:00+00:00", status="FAILED", generation=3),
    _prediction(DEN, "2026-10-28T12:00:00+00:00", winner="broncos", margin=2, p_home="0.55"),
    _prediction(NYJ, "2026-10-28T12:00:00+00:00", winner="raiders", margin=3, p_home="0.42"),
    _prediction(ORPHAN, "2026-10-28T12:00:00+00:00", winner="bills", margin=6, p_home="0.7"),
]


def seed_api() -> None:
    """Replace the contents of both NFL tables with the read-path set above."""
    ddb = boto3.resource("dynamodb", region_name=REGION)
    for env_var, keys, items in (("NFL_GAMES_TABLE", ("matchId",), GAMES),
                                 ("NFL_PREDICTIONS_TABLE", ("matchId", "generatedAt"), PREDICTIONS)):
        table = ddb.Table(os.environ[env_var])
        existing: list[dict] = []
        kwargs: dict = {}
        while True:
            resp = table.scan(**kwargs)
            existing.extend(resp["Items"])
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        # Two batches: one BatchWriteItem may not touch the same key twice.
        with table.batch_writer() as batch:
            for item in existing:
                batch.delete_item(Key={k: item[k] for k in keys})
        with table.batch_writer() as batch:
            for item in items:
                batch.put_item(Item=item)


def main() -> None:
    print("nfl_setup: creating tables ...")
    create_tables()
    print("nfl_setup: seeding the API read path ...")
    seed_api()
    print("nfl_setup: done")


if __name__ == "__main__":
    main()
