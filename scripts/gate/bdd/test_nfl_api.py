"""Step definitions for nfl_api.feature — the NFL API read path over HTTP
(spec Phase 4, criterion 4.9).

Runs against the gate-verify booted server (local_api_server.py routes /nfl/* to
nfl.api.router). Not collected by plain pytest — scripts/gate/ is outside
testpaths; the acceptance binding invokes `python -m pytest scripts/gate/bdd`.
The seed is written in-process to DynamoDB Local (same endpoint the server reads).
"""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from pytest_bdd import given, parsers, scenarios, then, when

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # scripts/gate/
from nfl_setup import seed_api  # noqa: E402

BASE = f"http://127.0.0.1:{os.environ.get('GATE_API_PORT', '8001')}"

scenarios("nfl_api.feature")


@given("the NFL API read-path seed is loaded")
def seeded() -> None:
    seed_api()


@when(parsers.parse('I GET "{path}"'), target_fixture="response")
def get(path: str) -> dict:
    req = urllib.request.Request(BASE + path)
    try:
        # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected -- fixed 127.0.0.1 base, only the port comes from GATE_API_PORT set by the gate runner
        with urllib.request.urlopen(req, timeout=10) as resp:
            return {
                "status": resp.status,
                "content_type": resp.headers.get("Content-Type", ""),
                "body": json.loads(resp.read().decode("utf-8")),
            }
    except urllib.error.HTTPError as e:
        return {
            "status": e.code,
            "content_type": e.headers.get("Content-Type", ""),
            "body": json.loads(e.read().decode("utf-8")),
        }


def _prediction(response: dict, match_id: str) -> dict:
    preds = {p["matchId"]: p for p in response["body"]}
    assert match_id in preds, f"{match_id} not in response ({sorted(preds)})"
    return preds[match_id]


@then(parsers.parse("the response status is {status:d}"))
def status_is(response: dict, status: int) -> None:
    assert response["status"] == status, f"got {response['status']}: {response['body']}"


@then("the response content type is JSON")
def content_type_json(response: dict) -> None:
    assert response["content_type"].startswith("application/json")


@then(parsers.parse('the response field "{field}" equals "{value}"'))
def field_equals(response: dict, field: str, value: str) -> None:
    assert response["body"].get(field) == value


@then(parsers.parse('the response field "{field}" is {value:d}'))
def field_is_int(response: dict, field: str, value: int) -> None:
    assert response["body"].get(field) == value


@then(parsers.parse("the response has fields {fields}"))
def has_fields(response: dict, fields: str) -> None:
    for field in (f.strip() for f in fields.split(",")):
        assert field in response["body"], f"{field} missing from {response['body']}"


@then("the response matchIds are, in order:")
def match_ids_in_order(response: dict, datatable) -> None:
    expected = [row[0] for row in datatable[1:]]
    assert [p["matchId"] for p in response["body"]] == expected


@then(parsers.parse('prediction "{match_id}" field "{field}" equals "{value}"'))
def pred_field_equals(response: dict, match_id: str, field: str, value: str) -> None:
    assert _prediction(response, match_id).get(field) == value


@then(parsers.parse('prediction "{match_id}" result home_score is {score:d}'))
def result_home_score(response: dict, match_id: str, score: int) -> None:
    assert _prediction(response, match_id).get("result", {}).get("home_score") == score


@then(parsers.parse('prediction "{match_id}" result winner is "{winner}"'))
def result_winner(response: dict, match_id: str, winner: str) -> None:
    assert _prediction(response, match_id).get("result", {}).get("winner") == winner


@then(parsers.parse('prediction "{match_id}" has no result'))
def no_result(response: dict, match_id: str) -> None:
    assert "result" not in _prediction(response, match_id)


@then(parsers.parse('prediction "{match_id}" is_outlier is true'))
def outlier_true(response: dict, match_id: str) -> None:
    assert _prediction(response, match_id).get("is_outlier") is True


@then(parsers.parse('prediction "{match_id}" is_outlier is false'))
def outlier_false(response: dict, match_id: str) -> None:
    assert _prediction(response, match_id).get("is_outlier") is False


@then(parsers.parse('prediction "{match_id}" has no is_outlier field'))
def no_outlier_field(response: dict, match_id: str) -> None:
    assert "is_outlier" not in _prediction(response, match_id)


@then(parsers.parse('prediction "{match_id}" market spread favourite is "{team}"'))
def spread_favourite(response: dict, match_id: str, team: str) -> None:
    assert _prediction(response, match_id).get("market", {}).get("spread_favourite") == team
