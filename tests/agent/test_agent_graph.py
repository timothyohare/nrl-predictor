import json
from unittest.mock import MagicMock, patch

import pytest
from moto import mock_aws

from v1.agent.graph import _execute_tool, run_agent
from v1.agent.schema import validate_prediction

MATCH_ID = "panthers-v-broncos-20260515"

_PREDICTION_JSON = json.dumps({
    "predicted_winner": "Panthers",
    "predicted_margin": 10,
    "confidence": "HIGH",
    "key_factors": ["Strong forward pack", "Cleary in form"],
    "reasoning": "x" * 200,
    "data_freshness": "2026-05-15T10:00:00Z",
    "model_used": "claude-haiku-4-5-20251001",
    "generated_at": "2026-05-15T11:00:00Z",
})


def _make_client(tool_calls=None, final_text=None):
    """
    Returns a mock Anthropic client.
    First call returns tool_use blocks (if tool_calls provided),
    second call returns the final prediction text.
    """
    client = MagicMock()

    def _make_response(content_blocks):
        resp = MagicMock()
        resp.content = content_blocks
        resp.usage = MagicMock(input_tokens=100, output_tokens=50)
        resp.stop_reason = "tool_use" if any(
            getattr(b, "type", None) == "tool_use" for b in content_blocks
        ) else "end_turn"
        return resp

    if tool_calls:
        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.id = "tu_001"
        tool_block.name = tool_calls[0]["name"]
        tool_block.input = tool_calls[0]["input"]

        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = final_text or _PREDICTION_JSON

        client.messages.create.side_effect = [
            _make_response([tool_block]),
            _make_response([text_block]),
        ]
    else:
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = final_text or _PREDICTION_JSON
        resp = _make_response([text_block])
        client.messages.create.return_value = resp

    return client


@pytest.fixture
def aws_env(monkeypatch):
    monkeypatch.setenv("TEAMS_TABLE", "teams")
    monkeypatch.setenv("RESULTS_TABLE", "results")
    monkeypatch.setenv("WEATHER_TABLE", "weather")
    monkeypatch.setenv("INJURIES_TABLE", "injuries")
    monkeypatch.setenv("CLAUDE_USAGE_TABLE", "claude_usage")


@mock_aws
def test_run_agent_returns_valid_prediction(aws_env, monkeypatch):
    client = _make_client()
    result = run_agent(MATCH_ID, {"is_finals": False}, client=client)
    validate_prediction(result)


def test_execute_tool_excludes_current_match_from_recent_form():
    """Regression test: get_recent_form must never see the match_id it's
    currently predicting, or a re-run against an already-scored match would
    leak the real result into "recent form"."""
    with patch("v1.agent.graph.get_recent_form") as mock_get_recent_form:
        _execute_tool("get_recent_form", {"team": "Panthers"}, MATCH_ID)
    mock_get_recent_form.assert_called_once_with(team="Panthers", exclude_match_id=MATCH_ID)


@mock_aws
def test_run_agent_calls_tool_then_produces_prediction(aws_env, monkeypatch):
    client = _make_client(
        tool_calls=[{"name": "get_team_sheet", "input": {"match_id": MATCH_ID, "round_number": 12}}],
        final_text=_PREDICTION_JSON,
    )
    with patch("v1.agent.graph._execute_tool", return_value={"homeTeam": "Panthers", "awayTeam": "Broncos"}):
        result = run_agent(MATCH_ID, {"is_finals": False}, client=client)
    assert client.messages.create.call_count == 2
    validate_prediction(result)


def _text_response(*texts):
    resp = MagicMock()
    blocks = []
    for t in texts:
        b = MagicMock()
        b.type = "text"
        b.text = t
        blocks.append(b)
    resp.content = blocks
    resp.usage = MagicMock(input_tokens=100, output_tokens=50)
    resp.stop_reason = "end_turn"
    return resp


_PROSE = "Now I have comprehensive data. Let me synthesize the analysis:\n\n## Analysis Summary ..."


@mock_aws
def test_run_agent_repairs_prose_output_with_followup_turn(aws_env):
    client = MagicMock()
    client.messages.create.side_effect = [
        _text_response(_PROSE),
        _text_response(_PREDICTION_JSON),
    ]
    result = run_agent(MATCH_ID, {"is_finals": False}, client=client)
    validate_prediction(result)
    assert client.messages.create.call_count == 2
    repair_messages = client.messages.create.call_args_list[1].kwargs["messages"]
    assert "only the prediction JSON" in json.dumps(repair_messages)


@mock_aws
def test_run_agent_fails_when_repair_turn_also_prose(aws_env):
    client = MagicMock()
    client.messages.create.side_effect = [
        _text_response(_PROSE),
        _text_response("Still just prose, sorry."),
    ]
    with pytest.raises(ValueError, match="non-JSON"):
        run_agent(MATCH_ID, {"is_finals": False}, client=client)
    assert client.messages.create.call_count == 2


@mock_aws
def test_run_agent_finds_json_in_later_text_block(aws_env):
    client = MagicMock()
    client.messages.create.return_value = _text_response(_PROSE, _PREDICTION_JSON)
    result = run_agent(MATCH_ID, {"is_finals": False}, client=client)
    validate_prediction(result)
    assert client.messages.create.call_count == 1


@mock_aws
def test_run_agent_includes_match_id_in_messages(aws_env):
    client = _make_client()
    run_agent(MATCH_ID, {"is_finals": False}, client=client)
    first_call = client.messages.create.call_args_list[0]
    # match_id should appear in the initial user message
    combined = json.dumps(first_call.kwargs)
    assert MATCH_ID in combined
