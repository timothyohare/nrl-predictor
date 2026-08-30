"""Second-stage seed for gate-verify: the async WRITE path.

`local_setup.py` builds the read-path tables (predictions / results / retrospectives
/ odds) and seeds round 12. This script adds the tables the write path also
touches — teams, injuries, weather, metrics — and a little canonical result
history so the Elo model has ratings to work from. It never drops or reseeds the
predictions/results tables `local_setup.py` owns; it only creates-if-absent and
adds rows under write-path-only round numbers (20-29), so read-path round 12 and
the write-path scenarios coexist in the same tables.

Run after `local_setup.py` (see the `setup` key in .claude/harness.json). Points
at DynamoDB Local via AWS_ENDPOINT_URL_DYNAMODB. Idempotent: drop-and-recreates
the four tables it owns; reruns start clean.
"""
import os
import time
from datetime import UTC, datetime, timedelta

import boto3
from botocore.exceptions import ClientError

REGION = os.environ.get("AWS_DEFAULT_REGION", "ap-southeast-2")

# Tables this script owns outright (env var, pk, sk) — drop-and-recreate each run.
OWNED_TABLES = [
    ("TEAMS_TABLE", "teamId", "round"),
    ("INJURIES_TABLE", "pk", "sk"),
    ("WEATHER_TABLE", "pk", "sk"),
    ("METRICS_TABLE", "period", "metricName"),
]

# Tables local_setup.py owns — only create if the standalone run skipped it.
SHARED_TABLES = [
    ("PREDICTIONS_TABLE", "matchId", "generatedAt"),
    ("RESULTS_TABLE", "matchId", "scoredAt"),
]

# Canonical result history (rounds 1-3) so compute_ratings_as_of has something to
# replay. Kept small — the walk-forward is instant and the scenarios only need
# the ratings to be non-degenerate.
_HISTORY = [
    ("round-1-panthers-v-broncos", "Panthers", "Broncos", 24, 12),
    ("round-1-storm-v-eels", "Storm", "Eels", 30, 10),
    ("round-1-roosters-v-rabbitohs", "Roosters", "Rabbitohs", 18, 16),
    ("round-2-broncos-v-storm", "Broncos", "Storm", 22, 20),
    ("round-2-eels-v-panthers", "Panthers", "Eels", 26, 14),
    ("round-2-rabbitohs-v-roosters", "Rabbitohs", "Roosters", 19, 12),
    ("round-3-panthers-v-storm", "Panthers", "Storm", 20, 18),
    ("round-3-broncos-v-eels", "Broncos", "Eels", 28, 22),
    ("round-3-roosters-v-storm", "Storm", "Roosters", 24, 10),
]


def _client():
    return boto3.client("dynamodb", region_name=REGION)


def _resource():
    return boto3.resource("dynamodb", region_name=REGION)


def _create(name: str, pk: str, sk: str | None) -> None:
    key_schema = [{"AttributeName": pk, "KeyType": "HASH"}]
    attrs = [{"AttributeName": pk, "AttributeType": "S"}]
    if sk:
        key_schema.append({"AttributeName": sk, "KeyType": "RANGE"})
        attrs.append({"AttributeName": sk, "AttributeType": "S"})
    _client().create_table(
        TableName=name,
        KeySchema=key_schema,
        AttributeDefinitions=attrs,
        BillingMode="PAY_PER_REQUEST",
    )
    _client().get_waiter("table_exists").wait(TableName=name)


def create_tables() -> None:
    client = _client()
    existing = set(client.list_tables()["TableNames"])

    for env_var, pk, sk in OWNED_TABLES:
        name = os.environ[env_var]
        try:
            client.delete_table(TableName=name)
            client.get_waiter("table_not_exists").wait(TableName=name)
        except ClientError:
            pass
        _create(name, pk, sk)
        print(f"  created {name}")

    for env_var, pk, sk in SHARED_TABLES:
        name = os.environ[env_var]
        if name not in existing:
            _create(name, pk, sk)
            print(f"  created {name} (standalone run — local_setup.py did not)")


def seed_history() -> None:
    results = _resource().Table(os.environ["RESULTS_TABLE"])
    for match_id, home, away, hs, aws in _HISTORY:
        winner = home if hs > aws else away
        results.put_item(Item={
            "matchId": match_id,
            "scoredAt": "2026-03-01T00:00:00Z",
            "roundNumber": int(match_id.split("-")[1]),
            "homeTeam": home,
            "awayTeam": away,
            "homeScore": hs,
            "awayScore": aws,
            "winner": winner,
            "margin": abs(hs - aws),
            "matchState": "FullTime",
        })
    print(f"  seeded {len(_HISTORY)} canonical history results (rounds 1-3)")


def seed_draw_kickoffs() -> None:
    """A teams `{matchId}#home` row per write-path fixture match, with a kickOff
    safely in the future so the scoring scenario scores a pre-kickoff prediction
    rather than falling back to hindsight mode."""
    teams = _resource().Table(os.environ["TEAMS_TABLE"])
    kick_off = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    # Mirrors tests/gate helper make_matches(): rounds 20-29, 3 matches each,
    # rotating through the same six clubs.
    clubs = ["panthers", "broncos", "storm", "eels", "roosters", "rabbitohs"]
    for rnd in range(20, 30):
        for i in range(3):
            home, away = clubs[(2 * i) % 6], clubs[(2 * i + 1) % 6]
            match_id = f"round-{rnd}-{home}-v-{away}"
            teams.put_item(Item={
                "teamId": f"{match_id}#home",
                "round": str(rnd),
                "matchId": match_id,
                "team": home,
                "kickOff": kick_off,
                "matchState": "Upcoming",
            })
    print("  seeded draw kickOff rows for rounds 20-29")


def main() -> None:
    print("write_path_setup: creating tables ...")
    create_tables()
    time.sleep(0.5)
    print("write_path_setup: seeding ...")
    seed_history()
    seed_draw_kickoffs()
    print("write_path_setup: done")


if __name__ == "__main__":
    main()
