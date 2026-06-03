"""Venue profile tool — returns ground characteristics and historical context."""

# Static venue profiles. NRL venues change sponsor names frequently, so we
# include common aliases. Characteristics like roof type and weather exposure
# don't change between seasons.
VENUE_PROFILES = {
    "accor-stadium": {
        "name": "Accor Stadium",
        "aliases": ["stadium australia", "anz stadium", "telstra stadium", "homebush"],
        "city": "Sydney",
        "capacity": 83500,
        "roof": "none",
        "surface": "grass",
        "weather_impact_notes": "Large open-air venue. Wind can swirl but generally not a major factor. Dew on surface late in evening games.",
    },
    "allianz-stadium": {
        "name": "Allianz Stadium",
        "aliases": ["sydney football stadium", "sfs", "moore park"],
        "city": "Sydney",
        "capacity": 42512,
        "roof": "partial",
        "surface": "grass",
        "weather_impact_notes": "Partial roof cover on grandstands. Moderate wind exposure. Good surface quality year-round.",
    },
    "4-pines-park": {
        "name": "4 Pines Park",
        "aliases": ["brookvale oval", "brookvale", "lottoland", "manly oval"],
        "city": "Sydney",
        "capacity": 18000,
        "roof": "none",
        "surface": "grass",
        "weather_impact_notes": "Notorious for swirling wind off the nearby headland. Wind neutralises kicking games and favours forward-dominant teams. Surface quality can deteriorate in winter.",
    },
    "blubet-stadium": {
        "name": "BlueBet Stadium",
        "aliases": ["penrith stadium", "panthers stadium", "pepper stadium", "creditunion australia stadium"],
        "city": "Penrith",
        "capacity": 22000,
        "roof": "none",
        "surface": "grass",
        "weather_impact_notes": "Western Sydney extremes — hot in summer, cold and foggy in winter. Dew and slippery surface late in evening games. Heat can exhaust visiting coastal teams.",
    },
    "commbank-stadium": {
        "name": "CommBank Stadium",
        "aliases": ["bankwest stadium", "parramatta stadium", "western sydney stadium"],
        "city": "Parramatta",
        "capacity": 30000,
        "roof": "partial",
        "surface": "grass",
        "weather_impact_notes": "Partially enclosed design reduces wind impact. Good surface. Western Sydney heat still a factor in summer but less exposed than BlueBet.",
    },
    "pointsbet-stadium": {
        "name": "PointsBet Stadium",
        "aliases": ["shark park", "remondis stadium", "endeavour field", "toyota stadium"],
        "city": "Sydney",
        "capacity": 22000,
        "roof": "none",
        "surface": "grass",
        "weather_impact_notes": "Coastal venue near Cronulla beach. Afternoon sea breeze can be significant. Generally mild conditions.",
    },
    "leichhardt-oval": {
        "name": "Leichhardt Oval",
        "aliases": ["leichhardt"],
        "city": "Sydney",
        "capacity": 20000,
        "roof": "none",
        "surface": "grass",
        "weather_impact_notes": "Tiny, hostile ground. Surface can be slippery in rain. Tight sidelines favour aggressive defence. Crowd very close to the action.",
    },
    "qld-country-bank-stadium": {
        "name": "Queensland Country Bank Stadium",
        "aliases": ["townsville stadium", "1300smiles stadium", "north queensland stadium"],
        "city": "Townsville",
        "capacity": 25000,
        "roof": "none",
        "surface": "grass",
        "weather_impact_notes": "Tropical heat and humidity exhausts visiting teams, especially Sydney sides. Evening games still warm and humid. Significant travel factor for southern teams.",
    },
    "suncorp-stadium": {
        "name": "Suncorp Stadium",
        "aliases": ["lang park", "brisbane stadium"],
        "city": "Brisbane",
        "capacity": 52500,
        "roof": "none",
        "surface": "grass",
        "weather_impact_notes": "Subtropical climate — warm and occasionally humid. Good quality surface. Enclosed feel despite no roof reduces wind. Brisbane heat less extreme than Townsville.",
    },
    "cbus-super-stadium": {
        "name": "Cbus Super Stadium",
        "aliases": ["robina stadium", "metricon stadium", "gold coast stadium", "heritage bank stadium"],
        "city": "Gold Coast",
        "capacity": 27400,
        "roof": "none",
        "surface": "grass",
        "weather_impact_notes": "Subtropical. Afternoon storms possible in summer. Generally good conditions. Titans have moderate home advantage due to travel for NSW teams.",
    },
    "mcdonald-jones-stadium": {
        "name": "McDonald Jones Stadium",
        "aliases": ["newcastle stadium", "hunter stadium", "energy australia stadium"],
        "city": "Newcastle",
        "capacity": 33000,
        "roof": "none",
        "surface": "grass",
        "weather_impact_notes": "Coastal venue. Can get windy. Generally mild. Newcastle fans create strong atmosphere when full.",
    },
    "win-stadium": {
        "name": "WIN Stadium",
        "aliases": ["wollongong stadium", "wollongong"],
        "city": "Wollongong",
        "capacity": 23000,
        "roof": "none",
        "surface": "grass",
        "weather_impact_notes": "Coastal ground exposed to wind off the escarpment. Can be cold in winter. Small ground favours aggressive defence.",
    },
    "gio-stadium": {
        "name": "GIO Stadium",
        "aliases": ["canberra stadium", "bruce stadium"],
        "city": "Canberra",
        "capacity": 25011,
        "roof": "none",
        "surface": "grass",
        "weather_impact_notes": "Inland Canberra — cold winters with frost, hot dry summers. Significant temperature extremes. Visiting teams often underperform in cold June-August games.",
    },
    "campbelltown-stadium": {
        "name": "Campbelltown Stadium",
        "aliases": ["campbelltown sports stadium", "c.ex stadium"],
        "city": "Campbelltown",
        "capacity": 21000,
        "roof": "none",
        "surface": "grass",
        "weather_impact_notes": "Western Sydney — similar extremes to Penrith. Hot summers, cold winters. Less wind than coastal venues.",
    },
    "go-media-stadium": {
        "name": "Go Media Stadium",
        "aliases": ["mt smart stadium", "mount smart", "auckland"],
        "city": "Auckland",
        "capacity": 30000,
        "roof": "none",
        "surface": "grass",
        "weather_impact_notes": "New Zealand — significant travel factor for all Australian teams. Can be wet and cold. Warriors have strong home advantage when crowd is engaged.",
    },
    "kayo-stadium": {
        "name": "Kayo Stadium",
        "aliases": ["redcliffe stadium", "dolphins stadium", "moreton daily stadium", "apollo projects stadium"],
        "city": "Redcliffe",
        "capacity": 11500,
        "roof": "none",
        "surface": "grass",
        "weather_impact_notes": "Small suburban ground in Queensland. Warm conditions. Intimate setting. Dolphins have built strong home record here.",
    },
}


def _slugify(name: str) -> str:
    """Convert venue name to a slug for matching."""
    import re
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _find_venue(venue_name: str) -> dict | None:
    """Find a venue profile by name, slug, or alias."""
    name_lower = venue_name.lower().strip()
    slug = _slugify(venue_name)

    for venue_slug, profile in VENUE_PROFILES.items():
        # Exact slug match
        if slug == venue_slug:
            return profile
        # Name match
        if name_lower == profile["name"].lower():
            return profile
        # Alias match
        for alias in profile.get("aliases", []):
            if name_lower == alias.lower() or alias.lower() in name_lower or name_lower in alias.lower():
                return profile
        # Partial name match
        if name_lower in profile["name"].lower() or profile["name"].lower() in name_lower:
            return profile

    return None


def get_venue_profile(venue: str) -> dict:
    """Return venue profile including characteristics and weather impact notes."""
    profile = _find_venue(venue)
    if profile:
        return {**profile, "known": True}
    return {
        "name": venue,
        "city": "Unknown",
        "capacity": 0,
        "roof": "unknown",
        "surface": "unknown",
        "weather_impact_notes": "No venue profile available. Use generic weather assessment.",
        "aliases": [],
        "known": False,
    }
