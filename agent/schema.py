from common.teams import is_known, to_slug

CONFIDENCE_LEVELS = {"LOW", "MEDIUM", "HIGH"}


class ValidationError(Exception):
    pass


def _normalise_team(name: str) -> str:
    """Resolve the model's team string to the canonical slug stored everywhere."""
    return to_slug(name)


def validate_prediction(raw: dict) -> dict:
    winner = _normalise_team(raw.get("predicted_winner", ""))
    raw["predicted_winner"] = winner
    if not is_known(winner):
        raise ValidationError(f"Unknown team: {winner!r}")
    confidence = raw.get("confidence", "")
    if confidence not in CONFIDENCE_LEVELS:
        raise ValidationError(f"Invalid confidence: {confidence!r}")
    factors = raw.get("key_factors", [])
    if len(factors) < 2:
        raise ValidationError(f"key_factors must have at least 2 items, got {len(factors)}")
    raw["key_factors"] = factors[:6]  # cap silently rather than reject
    return raw


def validate_player_names(reasoning: str, home_players: list[dict], away_players: list[dict]) -> bool:
    # Pass-through; deep validation (cross-checking team-sheet surnames against
    # the reasoning text) is a future enhancement.
    return True
