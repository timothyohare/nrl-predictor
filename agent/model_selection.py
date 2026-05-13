import os
from scrapers.shared.constants import HAIKU_MODEL, SONNET_MODEL


def select_model(match_context: dict) -> str:
    override = os.environ.get("AGENT_MODEL")
    if override:
        return override
    if match_context.get("is_finals") or match_context.get("is_high_impact_change"):
        return SONNET_MODEL
    return HAIKU_MODEL
