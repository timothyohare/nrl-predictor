"""Self-contained boot for the latency gate (gate-perf).

Unlike gate-verify — which stands up DynamoDB Local in Docker and tears it down
afterwards — gate-perf only spawns one boot process, waits for readiness, and
measures route latency. It does *not* manage a mock lifecycle. So this boot is
fully self-contained: it runs moto **in-process** (no Docker, no socket), seeds
the same round the verify gate uses, then serves the real API read path over
HTTP on the same port.

Keeping the data store in-process removes Docker/container variance from the
numbers, which is the point of a deterministic baseline — gate-perf measures
*our code's* cost, not the mock's.

Reuses `local_setup.create_tables`/`seed` and `local_api_server` so the perf
boot and the verify boot can never drift apart.

    .venv/bin/python scripts/gate/perf_boot.py
"""
import os

from moto import mock_aws

# moto intercepts boto3 at the HTTP layer; an explicit DynamoDB endpoint (set for
# the Docker-backed verify gate) would bypass it and hit a dead socket. Drop it
# before anything creates a boto3 client so every call lands on the in-process mock.
os.environ.pop("AWS_ENDPOINT_URL_DYNAMODB", None)

# Sensible defaults so this boots standalone; the harness's perfEnv still wins.
os.environ.setdefault("AWS_DEFAULT_REGION", "ap-southeast-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("GATE_API_PORT", "8001")
os.environ.setdefault("PREDICTIONS_TABLE", "predictions")
os.environ.setdefault("RESULTS_TABLE", "results")
os.environ.setdefault("RETROSPECTIVES_TABLE", "retrospectives")
os.environ.setdefault("ODDS_TABLE", "odds")
os.environ.setdefault("RATE_LIMITS_TABLE", "nrl-rate-limits")


def main() -> None:
    # Start the mock before importing anything that builds boto3 clients, and
    # keep it open for the life of the server (the process is killed by the gate).
    with mock_aws():
        # Sibling imports: this file is run as a script, so its own directory
        # (scripts/gate/) is on sys.path — same convention local_api_server uses.
        from local_setup import create_tables, seed

        print("perf_boot: creating in-process tables ...", flush=True)
        create_tables()
        print("perf_boot: seeding ...", flush=True)
        seed()

        # The router rate-limits to 20 req/hour per source IP (a fail-open
        # guardrail, hardcoded in api.rate_limit). Under gate-perf's warmup+sample
        # burst from a single IP it would trip and return 429, so unset the table
        # *after* seeding — the router skips the check when RATE_LIMITS_TABLE is
        # absent. We measure the join/handler cost, not the throttle.
        os.environ.pop("RATE_LIMITS_TABLE", None)

        from local_api_server import main as serve

        serve()


if __name__ == "__main__":
    main()
