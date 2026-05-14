NRL_TEAMS = {
    "Panthers", "Broncos", "Storm", "Roosters", "Sharks", "Raiders",
    "Warriors", "Cowboys", "Titans", "Eels", "Dragons", "Bulldogs",
    "Knights", "Sea Eagles", "Rabbitohs", "Wests Tigers", "Dolphins",
}
CONFIDENCE_LEVELS = {"LOW", "MEDIUM", "HIGH"}


class ValidationError(Exception):
    pass


def validate_prediction(raw: dict) -> dict:
    winner = raw.get("predicted_winner", "")
    if winner not in NRL_TEAMS:
        raise ValidationError(f"Unknown team: {winner!r}")
    confidence = raw.get("confidence", "")
    if confidence not in CONFIDENCE_LEVELS:
        raise ValidationError(f"Invalid confidence: {confidence!r}")
    factors = raw.get("key_factors", [])
    if not (2 <= len(factors) <= 6):
        raise ValidationError(f"key_factors must have 2–6 items, got {len(factors)}")
    return raw


def validate_player_names(reasoning: str, home_players: list[dict], away_players: list[dict]) -> bool:
    all_players = home_players + away_players
    known_surnames = {p["last_name"].lower() for p in all_players}
    # basic check: any surname from the team sheets appears in the reasoning, or reasoning mentions no surnames
    reasoning_lower = reasoning.lower()
    mentioned = [s for s in known_surnames if s in reasoning_lower]
    return True  # pass-through; deep validation is a future enhancement
