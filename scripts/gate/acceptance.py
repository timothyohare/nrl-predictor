"""Acceptance for gate-verify: prove the live API serves the joined read path
correctly against the seeded round (see local_setup.py).

Asserts the things that have actually broken in production before — a match
silently dropped because only its most-recent OK row should surface, the
result/retrospective/odds joins, and the is_outlier flag. Exits non-zero on the
first failed assertion so the gate fails loudly.
"""
import json
import os
import sys
import urllib.request

BASE = f"http://127.0.0.1:{os.environ.get('GATE_API_PORT', '8001')}"


def _get(path: str) -> tuple[int, dict | list]:
    req = urllib.request.Request(BASE + path)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def check(label: str, condition: bool) -> None:
    mark = "✓" if condition else "✗"
    print(f"  {mark} {label}")
    if not condition:
        failures.append(label)


failures: list[str] = []

# 1. Health
status, body = _get("/health")
check("GET /health → 200", status == 200)
check("health body status == ok", isinstance(body, dict) and body.get("status") == "ok")

# 2. The round join
status, preds = _get("/predictions/12")
check("GET /predictions/12 → 200", status == 200)
check("returns exactly 2 OK predictions (FAILED row excluded)", isinstance(preds, list) and len(preds) == 2)

if isinstance(preds, list) and len(preds) == 2:
    by_id = {p["matchId"]: p for p in preds}

    check("sorted by matchId", [p["matchId"] for p in preds] == sorted(by_id))

    panthers = by_id.get("round-12-panthers-v-broncos", {})
    # Most-recent generation wins (Panthers, not the superseded Broncos row).
    check("most-recent generation surfaces", panthers.get("predicted_winner") == "Panthers")
    check("result join present", panthers.get("result", {}).get("winner") == "Panthers")
    check("result carries scores", panthers.get("result", {}).get("homeScore") == 28)
    check("retrospective join present", bool(panthers.get("retrospective", {}).get("verdict")))
    check("odds join present", panthers.get("odds", {}).get("market_favourite") == "Panthers")
    check("agrees with market → not outlier", panthers.get("is_outlier") is False)

    storm = by_id.get("round-12-storm-v-eels", {})
    check("unplayed match has no result join", "result" not in storm)
    check("disagrees with market → outlier", storm.get("is_outlier") is True)

# 3. Empty round
status, body = _get("/predictions/99")
check("GET /predictions/99 → 404", status == 404)

if failures:
    print(f"\n✗ acceptance: {len(failures)} check(s) failed: {failures}")
    sys.exit(1)
print("\n✓ acceptance: all checks passed")
