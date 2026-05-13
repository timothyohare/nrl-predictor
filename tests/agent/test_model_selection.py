from agent.model_selection import select_model
from scrapers.shared.constants import HAIKU_MODEL, SONNET_MODEL


def test_standard_round_uses_haiku():
    ctx = {"is_finals": False, "is_high_impact_change": False}
    assert select_model(ctx) == HAIKU_MODEL


def test_finals_uses_sonnet():
    ctx = {"is_finals": True, "is_high_impact_change": False}
    assert select_model(ctx) == SONNET_MODEL


def test_high_impact_change_uses_sonnet():
    ctx = {"is_finals": False, "is_high_impact_change": True}
    assert select_model(ctx) == SONNET_MODEL
