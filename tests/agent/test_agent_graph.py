import json
from unittest.mock import MagicMock, patch

import pytest
from moto import mock_aws

from agent.graph import run_agent
from agent.schema import validate_prediction

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


@mock_aws
def test_run_agent_calls_tool_then_produces_prediction(aws_env, monkeypatch):
    client = _make_client(
        tool_calls=[{"name": "get_team_sheet", "input": {"match_id": MATCH_ID, "round_number": 12}}],
        final_text=_PREDICTION_JSON,
    )
    with patch("agent.graph._execute_tool", return_value={"homeTeam": "Panthers", "awayTeam": "Broncos"}):
        result = run_agent(MATCH_ID, {"is_finals": False}, client=client)
    assert client.messages.create.call_count == 2
    validate_prediction(result)


@mock_aws
def test_run_agent_includes_match_id_in_messages(aws_env):
    client = _make_client()
    run_agent(MATCH_ID, {"is_finals": False}, client=client)
    first_call = client.messages.create.call_args_list[0]
    # match_id should appear in the initial user message
    combined = json.dumps(first_call.kwargs)
    assert MATCH_ID in combined
