# Plan: Venue-Specific Models (Phase 7B)

## Goal

Build a venue profile database that captures how each NRL ground affects match outcomes — average scores, home win rate, weather impact at that specific venue, surface type, and dimensions. Replace the generic "check weather" step with venue-aware analysis: "Panthers at BlueBet in rain" becomes a first-class data point.

## Why This Matters

NRL venues have drastically different characteristics:
- **Brookvale Oval (4 Pines Park):** Notorious for wind — swirling gusts off the headland neutralise kicking games and favour forward-dominant teams
- **Queensland Country Bank Stadium (Townsville):** Heat and humidity exhaust visiting teams, especially Sydney sides not acclimatised
- **BlueBet Stadium (Penrith):** Western Sydney heat in summer, fog/dew in winter — surface gets slippery late in games
- **CommBank Stadium (Parramatta):** Enclosed roof partially mitigates weather — different profile from open-air grounds
- **Accor Stadium / Allianz Stadium:** Neutral-ish Sydney venues where crowd size varies wildly

The current agent treats all venues the same — it checks weather generically. A venue profile lets it reason: "Rain at Brookvale with existing wind = chaos; rain at CommBank with partial cover = minor impact."

## Data Model

### DynamoDB table: `venues`

| Field | Type | Description |
|-------|------|-------------|
| `venueId` (PK) | String | Slugified venue name, e.g. `4-pines-park` |
| `profile` (SK) | String | Always `"current"` for latest profile |
| `name` | String | Display name |
| `city` | String | City for weather lookups |
| `geohash` | String | 6-char BOM geohash for weather |
| `capacity` | Number | Seating capacity |
| `surface` | String | `grass` / `hybrid` |
| `roof` | String | `none` / `partial` / `retractable` |
| `avg_total_points` | Number | Historical average combined score at this venue |
| `home_win_rate` | Number | 0-1, historical home win rate |
| `avg_home_margin` | Number | Historical average margin when home team wins |
| `weather_impact_notes` | String | Human-written notes (e.g. "Swirling wind off headland") |
| `rain_home_win_rate` | Number | Home win rate on rainy days (if enough data) |
| `games_analysed` | Number | How many historical games informed the stats |
| `updatedAt` | String | ISO timestamp |

## Implementation Steps

### 1. [TEST] Write `tests/agent/test_tool_get_venue_profile.py`

- Test that `get_venue_profile(venue)` returns profile from DynamoDB
- Test fuzzy venue name matching (e.g. "4 Pines Park" matches "4-pines-park")
- Test fallback when venue not found (returns empty profile with warning)

### 2. [CODE] Create `agent/tools/venue_profile.py`

- `get_venue_profile(venue: str, table=None) -> dict`
- Fuzzy match venue name to `venueId` slug
- Returns all profile fields
- Falls back gracefully if venue not in database

### 3. [CODE] Register tool in `agent/graph.py`

- Add `get_venue_profile` to `_TOOL_DEFINITIONS` and `_execute_tool`
- Description: "Returns historical venue profile including home win rate, average scores, weather impact notes, and surface/roof info."

### 4. [CODE] Create `scripts/seed_venue_profiles.py`

- Seeds initial venue profiles from historical results data already in the `results` table
- For each venue: calculate home win rate, avg total points, avg home margin from all historical matches
- Manually annotate weather notes for the ~16 active NRL venues
- Run once, then update incrementally after each round

### 5. [CODE] Create `scripts/update_venue_stats.py`

- Reads completed results from the current season
- Recalculates rolling venue stats (last 2 seasons)
- Updates `venues` table
- Could be triggered weekly after results scraper runs

### 6. [CODE] Update `agent/prompt.py`

- Add step 4.5 between HOME/AWAY ADVANTAGE and WEATHER:
  "4b. VENUE PROFILE — Retrieve the venue profile. Factor in historical home win rate, surface conditions, and any known weather quirks specific to this ground."

### 7. [CODE] CDK updates

- New `venues` DynamoDB table (PK: `venueId`, SK: `profile`)
- Grant agent Lambda read access
- Add `VENUES_TABLE` env var to agent Lambda

### 8. [TEST] Integration test

- Verify agent calls `get_venue_profile` and incorporates it into reasoning

## Venue List (Active NRL 2026)

| Venue | City | Key Characteristic |
|-------|------|--------------------|
| Accor Stadium | Sydney | Large, neutral-ish |
| Allianz Stadium | Sydney | SCG precinct, moderate wind |
| 4 Pines Park (Brookvale) | Sydney | Wind, exposed, small |
| BlueBet Stadium | Penrith | Western Sydney heat/cold extremes |
| CommBank Stadium | Parramatta | Partially enclosed |
| PointsBet Stadium (Shark Park) | Sydney | Coastal wind |
| Leichhardt Oval | Sydney | Tiny, hostile, wet |
| Queensland Country Bank Stadium | Townsville | Heat, humidity |
| Suncorp Stadium | Brisbane | Enclosed, good surface |
| Cbus Super Stadium | Gold Coast | Subtropical |
| McDonald Jones Stadium | Newcastle | Coastal |
| WIN Stadium | Wollongong | Small, wind |
| GIO Stadium | Canberra | Cold, frost, altitude |
| Campbelltown Stadium | Sydney | Western Sydney |
| Go Media Stadium | Auckland | Travel factor |
| Apollo Projects Stadium | Brisbane | Dolphins home |

## Cost

- One-time seed script: reads existing results table (free)
- Ongoing: 1 DynamoDB read per match per agent call (~64/week = negligible)
- No new external API calls

## Risks

- **Venue name instability:** NRL venues change sponsor names frequently. Need a stable slug system with aliases.
- ABC Australia Sport network may have stable names for venues.
- **Small sample sizes:** Some venues host <10 games/season. Rolling 2-season window helps but stats will be noisy for smaller grounds.
- **Venue reassignment:** Teams occasionally play "home" games at neutral venues (Magic Round, Country Week). Need to handle these correctly.

## Definition of Done

- [ ] `venues` table seeded with profiles for all 16 active venues
- [ ] Agent calls `get_venue_profile` and references venue stats in reasoning
- [ ] Venue stats update automatically after each round
- [ ] Venue name fuzzy matching handles sponsor name changes
- [ ] Prompt updated with venue profile assessment step
