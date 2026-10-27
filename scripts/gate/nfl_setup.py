"""Third-stage seed for gate-verify: the NFL tables (spec Phase 3, criterion 3.10).

Creates `nfl_games` (PK matchId) and `nfl_predictions` (PK matchId, SK
generatedAt) in DynamoDB Local, mirroring infra/nfl_stack.py. The data itself is
not seeded here: the orchestrator ingests tests/fixtures/nfl_games_sample.csv over
file:// in the BDD steps, exactly as it would fetch the nflverse CSV live.

Run after `write_path_setup.py` (see the `setup` key in .claude/harness.json).
Owns only these two tables, so the NRL read/write-path tables are untouched.
Idempotent: drop-and-recreates both tables so reruns start clean.
"""
import os

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


def main() -> None:
    print("nfl_setup: creating tables ...")
    create_tables()
    print("nfl_setup: done")


if __name__ == "__main__":
    main()
