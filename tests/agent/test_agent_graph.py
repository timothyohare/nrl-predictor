import json
import sys
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import boto3
import pytest
from moto import mock_aws

from v1.agent.graph import (
    _REPAIR_INSTRUCTION,
    _execute_tool,
    _extract_prediction_json,
    _serialise,
    _with_cache_breakpoint,
    run_agent,
)
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


# --------------------------------------------------------------------------
# _extract_prediction_json — the four input shapes it must handle
# --------------------------------------------------------------------------

def _tb(text: str):
    """A minimal stand-in for an Anthropic text block (only ``.text`` is read)."""
    return SimpleNamespace(text=text)


def test_extract_prediction_json_from_fenced_block():
    fenced = f"Here is my answer:\n\n```json\n{_PREDICTION_JSON}\n```\n"
    parsed = _extract_prediction_json([_tb(fenced)])
    assert parsed is not None
    assert parsed["predicted_winner"] == "Panthers"


def test_extract_prediction_json_from_bare_single_block():
    parsed = _extract_prediction_json([_tb(_PREDICTION_JSON)])
    assert parsed is not None
    assert parsed["predicted_margin"] == 10


def test_extract_prediction_json_brace_span_across_concatenated_blocks():
    blocks = [
        _tb("Here is the prediction: {"),
        _tb('"predicted_winner": "Panthers", "predicted_margin": 10}'),
    ]
    parsed = _extract_prediction_json(blocks)
    assert parsed is not None
    assert parsed["predicted_winner"] == "Panthers"
    assert parsed["predicted_margin"] == 10


def test_extract_prediction_json_prose_only_returns_none():
    blocks = [_tb("I think the Panthers win by about ten points, but it will be close.")]
    assert _extract_prediction_json(blocks) is None


# --------------------------------------------------------------------------
# JSON-repair retry in run_agent
# --------------------------------------------------------------------------

@mock_aws
def test_run_agent_repair_turn_success_calls_client_exactly_twice(aws_env):
    client = MagicMock()
    client.messages.create.side_effect = [
        _text_response(_PROSE),
        _text_response(_PREDICTION_JSON),
    ]
    result = run_agent(MATCH_ID, {"is_finals": False}, client=client)
    validate_prediction(result)
    assert client.messages.create.call_count == 2
    repair_messages = client.messages.create.call_args_list[1].kwargs["messages"]
    assert _REPAIR_INSTRUCTION in json.dumps(repair_messages, ensure_ascii=False)


@mock_aws
def test_run_agent_repair_turn_also_prose_surfaces_failed_row_error(aws_env):
    client = MagicMock()
    client.messages.create.side_effect = [
        _text_response(_PROSE),
        _text_response("More prose. Still no JSON object here, sorry."),
    ]
    with pytest.raises(ValueError) as exc:
        run_agent(MATCH_ID, {"is_finals": False}, client=client)
    # The handler keys the FAILED row's `error` off this exact prefix.
    assert str(exc.value).startswith("Agent produced non-JSON output")
    assert client.messages.create.call_count == 2


# --------------------------------------------------------------------------
# Budget exceeded at lambda_handler entry → cached serve, agent never called
# --------------------------------------------------------------------------

@mock_aws
def test_lambda_handler_budget_exceeded_serves_cached_without_calling_agent(monkeypatch):
    monkeypatch.setenv("PREDICTIONS_TABLE", "predictions")
    monkeypatch.setenv("CLAUDE_USAGE_TABLE", "claude_usage")
    monkeypatch.setenv("MONTHLY_BUDGET_USD", "18")

    ddb = boto3.resource("dynamodb", region_name="ap-southeast-2")
    ddb.create_table(
        TableName="predictions",
        KeySchema=[
            {"AttributeName": "matchId", "KeyType": "HASH"},
            {"AttributeName": "generatedAt", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "matchId", "AttributeType": "S"},
            {"AttributeName": "generatedAt", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    ddb.create_table(
        TableName="claude_usage",
        KeySchema=[
            {"AttributeName": "yearMonth", "KeyType": "HASH"},
            {"AttributeName": "invokedAt", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "yearMonth", "AttributeType": "S"},
            {"AttributeName": "invokedAt", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    # Month-to-date spend already over the $18 threshold.
    ddb.Table("claude_usage").put_item(Item={
        "yearMonth": datetime.now(UTC).strftime("%Y-%m"),
        "invokedAt": "2026-01-01T00:00:00Z",
        "cost_usd": Decimal("25"),
    })
    # A prior OK prediction that should be re-served as stale.
    preds = ddb.Table("predictions")
    preds.put_item(Item={
        "matchId": MATCH_ID,
        "generatedAt": "2026-05-14T10:00:00Z",
        "status": "OK",
        "predicted_winner": "panthers",
        "staleness_flag": False,
    })

    fake_client = _make_client()
    with patch("v1.agent.lambda_handler.run_agent") as mock_run_agent:
        from v1.agent.lambda_handler import lambda_handler
        lambda_handler({"matchId": MATCH_ID, "round": 12}, {})

    mock_run_agent.assert_not_called()
    fake_client.messages.create.assert_not_called()

    served = [
        r for r in preds.scan()["Items"]
        if r["generatedAt"] != "2026-05-14T10:00:00Z"
    ]
    assert len(served) == 1
    assert served[0]["staleness_flag"] is True
    assert served[0]["status"] == "STALE"


# --------------------------------------------------------------------------
# _execute_tool dispatch
# --------------------------------------------------------------------------

@pytest.mark.parametrize("tool_name", [
    "get_team_sheet",
    "get_injury_list",
    "get_head_to_head",
    "get_weather",
    "get_ladder",
    "get_fantasy_stats",
    "get_venue_profile",
    "web_search",
    "get_lessons",
    "get_coaching_matchup",
    "detect_trap_game",
    "get_spine_synergy",
])
def test_execute_tool_dispatches_to_named_tool(tool_name):
    with patch(f"v1.agent.graph.{tool_name}") as mock_tool:
        mock_tool.return_value = {"ok": True}
        result = _execute_tool(tool_name, {"foo": "bar"}, MATCH_ID)
    mock_tool.assert_called_once_with(foo="bar")
    assert result == {"ok": True}


def test_execute_tool_unknown_name_raises_value_error():
    with pytest.raises(ValueError, match="Unknown tool: bogus_tool"):
        _execute_tool("bogus_tool", {}, MATCH_ID)


# --------------------------------------------------------------------------
# run_agent tool-execution error path + non-convergence
# --------------------------------------------------------------------------

def _tool_use_response(name="get_ladder", tool_input=None):
    block = SimpleNamespace(
        type="tool_use", id="tu_x", name=name, input=tool_input or {"season": 2026}
    )
    return _make_response_from_blocks([block])


def _make_response_from_blocks(blocks):
    resp = MagicMock()
    resp.content = blocks
    resp.usage = MagicMock(input_tokens=10, output_tokens=5)
    resp.stop_reason = "tool_use"
    return resp


@mock_aws
def test_run_agent_wraps_tool_error_as_error_tool_result(aws_env):
    client = MagicMock()
    client.messages.create.side_effect = [
        _tool_use_response(),
        _text_response(_PREDICTION_JSON),
    ]
    with patch("v1.agent.graph._execute_tool", side_effect=RuntimeError("boom")):
        result = run_agent(MATCH_ID, {"is_finals": False}, client=client)
    validate_prediction(result)
    second_call_messages = client.messages.create.call_args_list[1].kwargs["messages"]
    dumped = json.dumps(second_call_messages, default=str)
    assert "Error: boom" in dumped
    assert '"is_error": true' in dumped


@mock_aws
def test_run_agent_raises_when_it_never_converges(aws_env):
    client = MagicMock()
    client.messages.create.return_value = _tool_use_response()
    with patch("v1.agent.graph._execute_tool", return_value={"ladder": []}):
        with pytest.raises(RuntimeError, match="did not converge"):
            run_agent(MATCH_ID, {"is_finals": False}, client=client)


@mock_aws
def test_run_agent_builds_anthropic_client_from_secret_when_none(aws_env, monkeypatch):
    fake_anthropic = MagicMock()
    fake_anthropic.Anthropic.return_value = _make_client()
    monkeypatch.setitem(sys.modules, "anthropic", fake_anthropic)

    real_client = boto3.client

    def fake_boto3_client(name, *args, **kwargs):
        if name == "secretsmanager":
            m = MagicMock()
            m.get_secret_value.return_value = {"SecretString": "sk-ant-test"}
            return m
        return real_client(name, *args, **kwargs)

    monkeypatch.setattr("boto3.client", fake_boto3_client)

    result = run_agent(MATCH_ID, {"is_finals": False})
    validate_prediction(result)
    fake_anthropic.Anthropic.assert_called_once_with(api_key="sk-ant-test")


# --------------------------------------------------------------------------
# _serialise
# --------------------------------------------------------------------------

def test_serialise_round_trips_a_plain_object():
    assert json.loads(_serialise({"a": 1, "b": ["x"]})) == {"a": 1, "b": ["x"]}


def test_serialise_falls_back_to_str_when_json_dumps_raises():
    # Tuple keys are rejected by json even with default=str (default only
    # covers values), so this exercises the except branch.
    obj = {(1, 2): "v"}
    assert _serialise(obj) == str(obj)


# --------------------------------------------------------------------------
# _with_cache_breakpoint
# --------------------------------------------------------------------------

def test_with_cache_breakpoint_empty_list_unchanged():
    assert _with_cache_breakpoint([]) == []


def test_with_cache_breakpoint_promotes_string_content_to_block_list():
    out = _with_cache_breakpoint([{"role": "user", "content": "hi"}])
    assert out[0]["content"] == [
        {"type": "text", "text": "hi", "cache_control": {"type": "ephemeral"}}
    ]


def test_with_cache_breakpoint_marks_only_final_block_of_final_message():
    msgs = [
        {"role": "user", "content": [{"type": "text", "text": "a"}]},
        {"role": "assistant", "content": [
            {"type": "text", "text": "b"},
            {"type": "text", "text": "c"},
        ]},
    ]
    out = _with_cache_breakpoint(msgs)
    assert "cache_control" not in out[0]["content"][0]
    assert "cache_control" not in out[1]["content"][0]
    assert out[1]["content"][1]["cache_control"] == {"type": "ephemeral"}
    # source messages must not be mutated in place
    assert "cache_control" not in msgs[1]["content"][1]


def test_with_cache_breakpoint_empty_content_list_returned_unchanged():
    msgs = [{"role": "user", "content": []}]
    assert _with_cache_breakpoint(msgs) == msgs
