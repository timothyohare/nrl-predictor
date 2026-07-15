"""Step definitions for gate_api.feature (CHG-0025 behavioural acceptance).

Runs against the gate-verify booted app — NOT collected by plain pytest
(scripts/gate/ is outside testpaths); the acceptance binding invokes
`python -m pytest scripts/gate/bdd` explicitly.
"""
import json
import os
import urllib.error
import urllib.request

from pytest_bdd import parsers, scenarios, then, when

BASE = f"http://127.0.0.1:{os.environ.get('GATE_API_PORT', '8001')}"

scenarios("gate_api.feature")


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
    assert response["status"] == status, f"got {response['status']}"


@then(parsers.parse('the response field "{field}" equals "{value}"'))
def field_equals(response: dict, field: str, value: str) -> None:
    assert response["body"].get(field) == value


@then(parsers.parse("the response is a list of exactly {count:d} predictions"))
def list_of(response: dict, count: int) -> None:
    assert isinstance(response["body"], list)
    assert len(response["body"]) == count, f"got {len(response['body'])}"


@then("the predictions are sorted by matchId")
def sorted_by_match_id(response: dict) -> None:
    ids = [p["matchId"] for p in response["body"]]
    assert ids == sorted(ids)


@then(parsers.parse('prediction "{match_id}" field "{field}" equals "{value}"'))
def pred_field_equals(response: dict, match_id: str, field: str, value: str) -> None:
    assert _prediction(response, match_id).get(field) == value


@then(parsers.parse('prediction "{match_id}" result winner is "{winner}"'))
def result_winner(response: dict, match_id: str, winner: str) -> None:
    assert _prediction(response, match_id).get("result", {}).get("winner") == winner


@then(parsers.parse('prediction "{match_id}" result homeScore is {score:d}'))
def result_home_score(response: dict, match_id: str, score: int) -> None:
    assert _prediction(response, match_id).get("result", {}).get("homeScore") == score


@then(parsers.parse('prediction "{match_id}" has a retrospective verdict'))
def has_retrospective(response: dict, match_id: str) -> None:
    assert _prediction(response, match_id).get("retrospective", {}).get("verdict")


@then(parsers.parse('prediction "{match_id}" market favourite is "{team}"'))
def market_favourite(response: dict, match_id: str, team: str) -> None:
    assert _prediction(response, match_id).get("odds", {}).get("market_favourite") == team


@then(parsers.parse('prediction "{match_id}" outlier flag is false'))
def not_outlier(response: dict, match_id: str) -> None:
    assert _prediction(response, match_id).get("is_outlier") is False


@then(parsers.parse('prediction "{match_id}" outlier flag is true'))
def is_outlier(response: dict, match_id: str) -> None:
    assert _prediction(response, match_id).get("is_outlier") is True


@then(parsers.parse('prediction "{match_id}" has no result join'))
def no_result_join(response: dict, match_id: str) -> None:
    assert "result" not in _prediction(response, match_id)


@then("the response content type is JSON")
def content_type_json(response: dict) -> None:
    assert response["content_type"].startswith("application/json"), response["content_type"]
