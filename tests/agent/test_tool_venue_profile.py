from v1.agent.tools.venue_profile import VENUE_PROFILES, get_venue_profile


def test_exact_match():
    result = get_venue_profile("Suncorp Stadium")
    assert result["name"] == "Suncorp Stadium"
    assert "city" in result
    assert "roof" in result


def test_fuzzy_match():
    result = get_venue_profile("suncorp stadium")
    assert result["name"] == "Suncorp Stadium"


def test_partial_match():
    result = get_venue_profile("Suncorp")
    assert result["name"] == "Suncorp Stadium"


def test_alias_match():
    # "Lang Park" is an alias for Suncorp Stadium
    result = get_venue_profile("Lang Park")
    assert result["name"] == "Suncorp Stadium"


def test_unknown_venue():
    result = get_venue_profile("Nonexistent Stadium")
    assert result["name"] == "Nonexistent Stadium"
    assert result["known"] is False
    assert "No venue profile available" in result["weather_impact_notes"]


def test_all_profiles_have_required_fields():
    required = {"name", "city", "roof", "surface", "weather_impact_notes"}
    for slug, profile in VENUE_PROFILES.items():
        for field in required:
            assert field in profile, f"Missing '{field}' in venue profile '{slug}'"


def test_brookvale_has_wind_notes():
    result = get_venue_profile("4 Pines Park")
    assert "wind" in result["weather_impact_notes"].lower()
