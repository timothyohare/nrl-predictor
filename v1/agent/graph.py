"""
LangGraph-style ReAct agent implemented directly with the Anthropic SDK.
Each invocation is a single Lambda call; tool results are appended to the
message history until Claude produces a text-only response.
"""
import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

from v1.agent.budget import record_usage
from v1.agent.model_selection import select_model
from v1.agent.prompt import build_system_prompt
from v1.agent.schema import validate_prediction
from v1.agent.tools.coaching_matchup import get_coaching_matchup
from v1.agent.tools.fantasy_stats import get_fantasy_stats
from v1.agent.tools.head_to_head import get_head_to_head
from v1.agent.tools.injury_list import get_injury_list
from v1.agent.tools.ladder import get_ladder
from v1.agent.tools.lessons import get_lessons
from v1.agent.tools.recent_form import get_recent_form
from v1.agent.tools.spine_synergy import get_spine_synergy
from v1.agent.tools.team_sheet import get_team_sheet
from v1.agent.tools.trap_game import detect_trap_game
from v1.agent.tools.venue_profile import get_venue_profile
from v1.agent.tools.weather import get_weather
from v1.agent.tools.web_search import web_search

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 10

_TOOL_DEFINITIONS = [
    {
        "name": "get_team_sheet",
        "description": "Returns the official starting 1-17 + bench for a team and round from DynamoDB.",
        "input_schema": {
            "type": "object",
            "properties": {
                "match_id": {"type": "string"},
                "round_number": {"type": "integer"},
            },
            "required": ["match_id", "round_number"],
        },
    },
    {
        "name": "get_injury_list",
        "description": "Returns current injury/unavailability list for a team.",
        "input_schema": {
            "type": "object",
            "properties": {"team": {"type": "string"}},
            "required": ["team"],
        },
    },
    {
        "name": "get_recent_form",
        "description": "Returns the last n match results for a team with momentum analysis: weighted win rate, momentum direction (rising/falling/stable), current streak, and weighted scoring trends.",
        "input_schema": {
            "type": "object",
            "properties": {
                "team": {"type": "string"},
                "n": {"type": "integer", "default": 5},
            },
            "required": ["team"],
        },
    },
    {
        "name": "get_head_to_head",
        "description": "Returns historical head-to-head record between two teams, optionally filtered by venue.",
        "input_schema": {
            "type": "object",
            "properties": {
                "team_a": {"type": "string"},
                "team_b": {"type": "string"},
                "venue": {"type": "string"},
            },
            "required": ["team_a", "team_b"],
        },
    },
    {
        "name": "get_weather",
        "description": "Returns the venue weather forecast for a match date.",
        "input_schema": {
            "type": "object",
            "properties": {
                "venue": {"type": "string"},
                "date": {"type": "string", "description": "YYYY-MM-DD"},
            },
            "required": ["venue", "date"],
        },
    },
    {
        "name": "get_ladder",
        "description": "Returns the current NRL ladder sorted by position.",
        "input_schema": {
            "type": "object",
            "properties": {"season": {"type": "integer"}},
            "required": ["season"],
        },
    },
    {
        "name": "get_fantasy_stats",
        "description": (
            "Returns NRL Fantasy availability and price-signal data for a team. "
            "Includes confirmed unavailable players (injured/suspended/not-playing), "
            "uncertain players, and playing players whose fantasy price has dropped "
            ">5% from peak (early signal of undisclosed rest or injury)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"team": {"type": "string", "description": "Team nickname e.g. Panthers"}},
            "required": ["team"],
        },
    },
    {
        "name": "web_search",
        "description": "Live web search for breaking news not yet in the local corpus.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "get_coaching_matchup",
        "description": (
            "Returns the head-to-head record between the current coaches of two teams. "
            "Only counts games during both coaches' tenures — ignores results under different coaches."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "team_a": {"type": "string", "description": "Team nickname, e.g. 'Panthers'"},
                "team_b": {"type": "string", "description": "Team nickname, e.g. 'Storm'"},
            },
            "required": ["team_a", "team_b"],
        },
    },
    {
        "name": "get_venue_profile",
        "description": (
            "Returns venue profile including roof type, surface, capacity, city, "
            "and weather impact notes specific to this ground. Use to understand "
            "how the venue affects match conditions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "venue": {"type": "string", "description": "Venue name, e.g. 'Suncorp Stadium'"},
            },
            "required": ["venue"],
        },
    },
    {
        "name": "get_lessons",
        "description": (
            "Returns lessons learned from post-match retrospectives. "
            "Use to check what past predictions got wrong for a team or matchup type."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "season": {"type": "integer"},
                "team": {"type": "string", "description": "Team slug to filter by, e.g. 'panthers'"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["season"],
        },
    },
    {
        "name": "detect_trap_game",
        "description": (
            "Analyses schedule context to detect trap game conditions: sandwich games "
            "between tough opponents, emotional letdowns after big wins, dead rubbers, "
            "and revenge games. Returns a trap score (0-5) with explanations."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "match_id": {"type": "string"},
                "round_number": {"type": "integer"},
                "season": {"type": "integer"},
                "home_team": {"type": "string", "description": "Home team nickname"},
                "away_team": {"type": "string", "description": "Away team nickname"},
            },
            "required": ["match_id", "round_number", "season", "home_team", "away_team"],
        },
    },
    {
        "name": "get_spine_synergy",
        "description": (
            "Analyses how many games each team's spine (fullback 1, five-eighth 6, halfback 7, hooker 9) "
            "have played together this season. Flags new combinations with <5 games together as a vulnerability."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "match_id": {"type": "string"},
                "round_number": {"type": "integer"},
            },
            "required": ["match_id", "round_number"],
        },
    },
]


def _execute_tool(name: str, tool_input: dict) -> object:
    if name == "get_team_sheet":
        return get_team_sheet(**tool_input)
    if name == "get_injury_list":
        return get_injury_list(**tool_input)
    if name == "get_recent_form":
        return get_recent_form(**tool_input)
    if name == "get_head_to_head":
        return get_head_to_head(**tool_input)
    if name == "get_weather":
        return get_weather(**tool_input)
    if name == "get_ladder":
        return get_ladder(**tool_input)
    if name == "get_fantasy_stats":
        return get_fantasy_stats(**tool_input)
    if name == "get_venue_profile":
        return get_venue_profile(**tool_input)
    if name == "web_search":
        return web_search(**tool_input)
    if name == "get_lessons":
        return get_lessons(**tool_input)
    if name == "get_coaching_matchup":
        return get_coaching_matchup(**tool_input)
    if name == "detect_trap_game":
        return detect_trap_game(**tool_input)
    if name == "get_spine_synergy":
        return get_spine_synergy(**tool_input)
    raise ValueError(f"Unknown tool: {name}")


def _extract_prediction_json(text_blocks) -> dict | None:
    """Find the prediction JSON object anywhere in the final text blocks."""
    joined = "\n".join(b.text for b in text_blocks)
    candidates = []
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", joined, re.DOTALL)
    if fence_match:
        candidates.append(fence_match.group(1))
    candidates.extend(b.text.strip() for b in text_blocks)
    if "{" in joined and "}" in joined:
        candidates.append(joined[joined.index("{"): joined.rindex("}") + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


_REPAIR_INSTRUCTION = (
    "Return only the prediction JSON object, no other text. "
    "Do not repeat your analysis — output the single JSON object matching the required schema."
)


def _serialise(obj) -> str:
    try:
        return json.dumps(obj, default=str)
    except Exception:
        return str(obj)


def run_agent(match_id: str, match_context: dict, client=None,
              system_prompt: str | None = None) -> dict:
    model = select_model(match_context)

    if client is None:
        import anthropic
        import boto3
        secret = boto3.client("secretsmanager").get_secret_value(
            SecretId="nrl-predictor/anthropic-api-key"
        )
        api_key = secret["SecretString"]
        client = anthropic.Anthropic(api_key=api_key)

    system = system_prompt if system_prompt is not None else build_system_prompt(
        lessons=match_context.get("lessons")
    )
    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": (
                f"Analyse this match and produce a prediction.\n\n"
                f"match_id: {match_id}\n"
                f"context: {_serialise(match_context)}\n\n"
                "Use the available tools to gather team sheets, injury lists, recent form, "
                "head-to-head records, weather and any breaking news before producing your prediction."
            ),
        }
    ]

    total_input = total_output = 0
    repair_attempted = False

    for _iteration in range(MAX_ITERATIONS):
        response = client.messages.create(
            model=model,
            max_tokens=2048,
            system=system,
            tools=_TOOL_DEFINITIONS,
            messages=messages,
        )
        total_input += response.usage.input_tokens
        total_output += response.usage.output_tokens

        tool_uses = [b for b in response.content if getattr(b, "type", None) == "tool_use"]
        text_blocks = [b for b in response.content if getattr(b, "type", None) == "text"]

        if not tool_uses:
            raw_text = "\n".join(b.text for b in text_blocks)
            prediction = _extract_prediction_json(text_blocks)
            if prediction is None:
                if not repair_attempted:
                    # One follow-up turn asking for the JSON only, then give up
                    repair_attempted = True
                    logger.warning(
                        "Agent emitted prose for %s — attempting JSON repair turn", match_id
                    )
                    messages.append({"role": "assistant", "content": raw_text or "(empty)"})
                    messages.append({"role": "user", "content": _REPAIR_INSTRUCTION})
                    continue
                raise ValueError(f"Agent produced non-JSON output: {raw_text[:200]}")

            prediction["model_used"] = model
            prediction["generated_at"] = datetime.now(UTC).isoformat()

            try:
                record_usage(total_input, total_output, model)
            except Exception:
                logger.warning("Failed to record usage", exc_info=True)

            return validate_prediction(prediction)

        # Append assistant message with tool_use blocks
        messages.append({"role": "assistant", "content": response.content})

        # Execute each tool and append tool_result
        tool_results = []
        for block in tool_uses:
            try:
                result = _execute_tool(block.name, block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": _serialise(result),
                })
            except Exception as e:
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": f"Error: {e}",
                    "is_error": True,
                })

        messages.append({"role": "user", "content": tool_results})

    raise RuntimeError(f"Agent did not converge after {MAX_ITERATIONS} iterations for {match_id}")
