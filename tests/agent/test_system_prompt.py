from agent.prompt import build_system_prompt


def test_returns_non_empty_string():
    assert len(build_system_prompt()) > 0


def test_contains_cite_instruction():
    assert "cite" in build_system_prompt().lower()


def test_contains_schema_field_names():
    prompt = build_system_prompt()
    assert "predicted_winner" in prompt
    assert "confidence" in prompt
    assert "key_factors" in prompt
    assert "reasoning" in prompt


def test_contains_uncertainty_instruction():
    prompt = build_system_prompt().lower()
    assert "uncertain" in prompt or "missing" in prompt or "flag" in prompt
