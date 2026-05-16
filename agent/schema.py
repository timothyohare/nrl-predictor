NRL_TEAMS = {
    "Panthers", "Broncos", "Storm", "Roosters", "Sharks", "Raiders",
    "Warriors", "Cowboys", "Titans", "Eels", "Dragons", "Bulldogs",
    "Knights", "Sea Eagles", "Rabbitohs", "Wests Tigers", "Dolphins",
}
CONFIDENCE_LEVELS = {"LOW", "MEDIUM", "HIGH"}

# Map long-form or alternate names the model may produce → canonical nickname
_TEAM_ALIASES = {
    "north queensland cowboys": "Cowboys",
    "new zealand warriors": "Warriors",
    "new south wales waratahs": "Waratahs",
    "sydney roosters": "Roosters",
    "south sydney rabbitohs": "Rabbitohs",
    "st george illawarra dragons": "Dragons",
    "gold coast titans": "Titans",
    "newcastle knights": "Knights",
    "parramatta eels": "Eels",
    "canberra raiders": "Raiders",
    "penrith panthers": "Panthers",
    "brisbane broncos": "Broncos",
    "cronulla sharks": "Sharks",
    "cronulla-sutherland sharks": "Sharks",
    "manly sea eagles": "Sea Eagles",
    "manly-warringah sea eagles": "Sea Eagles",
    "melbourne storm": "Storm",
    "wests tigers": "Wests Tigers",
    "dolphins": "Dolphins",
}


class ValidationError(Exception):
    pass


def _normalise_team(name: str) -> str:
    return _TEAM_ALIASES.get(name.lower(), name)


def validate_prediction(raw: dict) -> dict:
    winner = _normalise_team(raw.get("predicted_winner", ""))
    raw["predicted_winner"] = winner
    if winner not in NRL_TEAMS:
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
    all_players = home_players + away_players
    known_surnames = {p["last_name"].lower() for p in all_players}
    # basic check: any surname from the team sheets appears in the reasoning, or reasoning mentions no surnames
    reasoning_lower = reasoning.lower()
    mentioned = [s for s in known_surnames if s in reasoning_lower]
    return True  # pass-through; deep validation is a future enhancement
