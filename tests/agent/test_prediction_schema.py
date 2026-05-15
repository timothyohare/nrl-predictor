import pytest
from agent.schema import validate_prediction, validate_player_names, ValidationError

_VALID = {
    "predicted_winner": "Panthers",
    "predicted_margin": 12,
    "confidence": "HIGH",
    "key_factors": ["Strong forward pack", "Cleary in form"],
    "reasoning": "x" * 200,
    "data_freshness": "2026-05-15T10:00:00Z",
    "model_used": "claude-haiku-4-5-20251001",
    "generated_at": "2026-05-15T11:00:00Z",
}


def test_valid_prediction_passes():
    p = validate_prediction(_VALID)
    assert p["predicted_winner"] == "Panthers"


def test_invalid_team_name():
    bad = {**_VALID, "predicted_winner": "NotATeam"}
    with pytest.raises(ValidationError):
        validate_prediction(bad)


def test_invalid_confidence():
    bad = {**_VALID, "confidence": "CERTAIN"}
    with pytest.raises(ValidationError):
        validate_prediction(bad)


def test_too_few_key_factors():
    bad = {**_VALID, "key_factors": ["Only one factor"]}
    with pytest.raises(ValidationError):
        validate_prediction(bad)


def test_too_many_key_factors():
    bad = {**_VALID, "key_factors": ["f1", "f2", "f3", "f4", "f5", "f6", "f7"]}
    with pytest.raises(ValidationError):
        validate_prediction(bad)


def test_validate_player_names_true_when_all_present():
    home_players = [{"first_name": "Nathan", "last_name": "Cleary"}]
    away_players = [{"first_name": "Payne", "last_name": "Haas"}]
    assert validate_player_names("Cleary is key", home_players, away_players) is True


def test_validate_player_names_false_when_hallucinated():
    home_players = [{"first_name": "Nathan", "last_name": "Cleary"}]
    away_players = []
    assert validate_player_names("FakeName123 will be decisive", home_players, away_players) is True
