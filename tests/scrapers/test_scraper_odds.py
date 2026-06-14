from unittest.mock import MagicMock

from scrapers.odds.scraper import TEAM_NAME_MAP, fetch_odds, parse_odds

# Sample response from the-odds-api.com
SAMPLE_API_RESPONSE = [
    {
        "id": "abc123",
        "sport_key": "rugbyleague_nrl",
        "sport_title": "NRL",
        "commence_time": "2026-06-07T09:50:00Z",
        "home_team": "Penrith Panthers",
        "away_team": "Canterbury Bulldogs",
        "bookmakers": [
            {
                "key": "sportsbet",
                "title": "Sportsbet",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Penrith Panthers", "price": 1.45},
                            {"name": "Canterbury Bulldogs", "price": 2.80},
                        ]
                    },
                    {
                        "key": "spreads",
                        "outcomes": [
                            {"name": "Penrith Panthers", "price": 1.90, "point": -6.5},
                            {"name": "Canterbury Bulldogs", "price": 1.90, "point": 6.5},
                        ]
                    },
                ]
            },
            {
                "key": "tab",
                "title": "TAB",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Penrith Panthers", "price": 1.50},
                            {"name": "Canterbury Bulldogs", "price": 2.60},
                        ]
                    },
                    {
                        "key": "spreads",
                        "outcomes": [
                            {"name": "Penrith Panthers", "price": 1.85, "point": -7.5},
                            {"name": "Canterbury Bulldogs", "price": 1.95, "point": 7.5},
                        ]
                    },
                ]
            },
        ]
    },
    {
        "id": "def456",
        "sport_key": "rugbyleague_nrl",
        "sport_title": "NRL",
        "commence_time": "2026-06-07T19:50:00Z",
        "home_team": "Melbourne Storm",
        "away_team": "Sydney Roosters",
        "bookmakers": [
            {
                "key": "sportsbet",
                "title": "Sportsbet",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Melbourne Storm", "price": 1.60},
                            {"name": "Sydney Roosters", "price": 2.35},
                        ]
                    },
                ]
            },
        ]
    },
]

# Round matches for matchId mapping
ROUND_MATCHES = [
    {"match_id": "round-15-panthers-v-bulldogs", "home_team": "Panthers", "away_team": "Bulldogs"},
    {"match_id": "round-15-storm-v-roosters", "home_team": "Storm", "away_team": "Roosters"},
]


def test_team_name_map_covers_all_teams():
    """All 17 NRL teams should have a mapping."""
    teams = {
        "Panthers", "Storm", "Roosters", "Broncos", "Sharks", "Cowboys",
        "Bulldogs", "Sea Eagles", "Rabbitohs", "Eels", "Knights", "Raiders",
        "Warriors", "Titans", "Dragons", "Dolphins", "Wests Tigers",
    }
    mapped_teams = set(TEAM_NAME_MAP.values())
    assert teams.issubset(mapped_teams)


def test_parse_odds_h2h():
    """Should extract head-to-head odds and average across bookmakers."""
    result = parse_odds(SAMPLE_API_RESPONSE, ROUND_MATCHES)
    assert len(result) == 2

    panthers_odds = result[0]
    assert panthers_odds["matchId"] == "round-15-panthers-v-bulldogs"
    assert panthers_odds["market_favourite"] == "Panthers"
    # Average home odds: (1.45 + 1.50) / 2 = 1.475
    assert abs(panthers_odds["home_odds"] - 1.475) < 0.01
    # Average away odds: (2.80 + 2.60) / 2 = 2.70
    assert abs(panthers_odds["away_odds"] - 2.70) < 0.01


def test_parse_odds_spreads():
    """Should extract spread/line from bookmakers."""
    result = parse_odds(SAMPLE_API_RESPONSE, ROUND_MATCHES)
    panthers_odds = result[0]
    # Average spread: (6.5 + 7.5) / 2 = 7.0
    assert abs(panthers_odds["market_margin"] - 7.0) < 0.01


def test_implied_probability():
    """Should calculate normalised implied probabilities."""
    result = parse_odds(SAMPLE_API_RESPONSE, ROUND_MATCHES)
    panthers_odds = result[0]
    # Implied probs should sum to ~1.0 after normalisation
    total = panthers_odds["implied_home_prob"] + panthers_odds["implied_away_prob"]
    assert abs(total - 1.0) < 0.01
    # Home team should have higher implied prob
    assert panthers_odds["implied_home_prob"] > panthers_odds["implied_away_prob"]


def test_no_spread_market():
    """Match with only h2h market should still work (margin = 0)."""
    result = parse_odds(SAMPLE_API_RESPONSE, ROUND_MATCHES)
    storm_odds = result[1]
    assert storm_odds["matchId"] == "round-15-storm-v-roosters"
    # Only 1 bookmaker, no spread market
    assert storm_odds["market_margin"] == 0


def test_unmatched_game_skipped():
    """API game that doesn't match any round match should be skipped."""
    extra_game = [{
        "id": "xyz",
        "sport_key": "rugbyleague_nrl",
        "commence_time": "2026-06-07T09:50:00Z",
        "home_team": "Gold Coast Titans",
        "away_team": "New Zealand Warriors",
        "bookmakers": [],
    }]
    result = parse_odds(extra_game, ROUND_MATCHES)
    assert len(result) == 0


def test_fetch_odds_calls_api(monkeypatch):
    """fetch_odds should call the API with the correct parameters."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = SAMPLE_API_RESPONSE

    mock_get = MagicMock(return_value=mock_resp)
    monkeypatch.setattr("scrapers.odds.scraper.requests.get", mock_get)

    result = fetch_odds(api_key="test-key")
    assert result == SAMPLE_API_RESPONSE
    mock_get.assert_called_once()
    call_args = mock_get.call_args
    assert "test-key" in call_args[1].get("params", {}).get("apiKey", "")
