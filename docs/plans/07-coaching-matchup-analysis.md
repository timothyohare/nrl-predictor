# Plan: Coaching Matchup Analysis (Phase 7D)

## Goal

Add coach-vs-coach historical records as a tool the agent can query. Certain coaches consistently outperform against others regardless of roster quality — this captures tactical tendencies that player stats miss.

## Why This Matters

NRL coaching matchups create persistent edges:
- **Craig Bellamy (Storm)** has historically dominated Wayne Bennett-coached teams in finals
- **Ivan Cleary (Panthers)** struggled against Trent Robinson (Roosters) in 2019-2021 before the tide turned
- **Some coaches consistently overperform against top-4 teams** (upset specialists) while others fold under pressure
- **Tactical adaptations:** Coaches who've lost to an opponent recently often adjust specifically for the rematch — the most recent H2H result matters more than the 5-year record

Current H2H data is team-based, not coach-based. A team's H2H record under a different coach is misleading — Bulldogs under Ciraldo are a fundamentally different team than Bulldogs under Barrett.

## Data Model

### DynamoDB table: `coaches`

| Field | Type | Description |
|-------|------|-------------|
| `coachId` (PK) | String | Slugified name, e.g. `craig-bellamy` |
| `profile` (SK) | String | `"current"` for active profile, or `"{season}"` for seasonal snapshot |
| `name` | String | Display name |
| `team` | String | Current team nickname |
| `seasons_at_team` | Number | Tenure |
| `career_win_rate` | Number | 0-1 |
| `current_season_win_rate` | Number | 0-1 |
| `updatedAt` | String | ISO timestamp |

### DynamoDB table: `coach_matchups`

| Field | Type | Description |
|-------|------|-------------|
| `matchupId` (PK) | String | `{coach_a_slug}-v-{coach_b_slug}` (alphabetical) |
| `scrapedAt` (SK) | String | ISO timestamp |
| `coach_a` | String | Coach name |
| `coach_b` | String | Coach name |
| `coach_a_team` | String | Current team |
| `coach_b_team` | String | Current team |
| `total_games` | Number | Total meetings |
| `coach_a_wins` | Number | |
| `coach_b_wins` | Number | |
| `draws` | Number | |
| `last_3` | List | Last 3 results with dates and scores |
| `coach_a_win_rate` | Number | 0-1 |
| `notes` | String | e.g. "Bellamy 8-2 since 2022 when Storm switched to..." |

## Data Source

Coach data isn't available from a single structured API. Options:

1. **NRL.com team pages** — list current head coach per team. Scrape once, update when coaching changes happen (rare mid-season).
2. **Historical coach records** — derive from our existing `results` table by mapping team+season to coach (maintain a `coach_history` lookup: `{ "Panthers": [{"coach": "Ivan Cleary", "from": "2019", "to": null}] }`).
3. **Web search fallback** — agent can use `web_search` for specific coaching matchup queries.

The simplest approach: maintain a static `COACH_MAP` in code (coaches change ~2-3 times per season across all teams) and compute matchup records from the `results` table.

## Implementation Steps

### 1. [CODE] Create `scrapers/shared/coach_map.py`

Static mapping of team → coach with date ranges:

```python
COACH_MAP = {
    "Panthers": [{"coach": "Ivan Cleary", "from": "2019-01-01", "to": None}],
    "Storm": [{"coach": "Craig Bellamy", "from": "2003-01-01", "to": None}],
    "Roosters": [{"coach": "Trent Robinson", "from": "2013-01-01", "to": None}],
    # ...
}
```

Update this when coaching changes happen (2-3 times per year at most).

### 2. [TEST] Write `tests/agent/test_tool_get_coaching_matchup.py`

- Test `get_coaching_matchup(team_a, team_b)` returns coach records
- Test that results are filtered to current coaches' tenures only
- Test edge case: new coach with <3 games against opponent
- Test coach lookup from team name

### 3. [CODE] Create `agent/tools/coaching_matchup.py`

- `get_coaching_matchup(team_a: str, team_b: str, table=None) -> dict`
- Looks up current coaches for both teams from `COACH_MAP`
- Queries `results` table for matches between the teams during both coaches' tenures
- Computes win/loss record, last 3 meetings, and notes
- Returns:
  ```python
  {
      "coach_a": {"name": "Ivan Cleary", "team": "Panthers", "tenure_start": "2019"},
      "coach_b": {"name": "Craig Bellamy", "team": "Storm", "tenure_start": "2003"},
      "record": {"a_wins": 5, "b_wins": 8, "draws": 0},
      "last_3": [...],
      "edge": "Storm (Bellamy has a 61.5% win rate against Cleary)"
  }
  ```

### 4. [CODE] Register tool in `agent/graph.py`

- Add `get_coaching_matchup` to `_TOOL_DEFINITIONS` and `_execute_tool`
- Description: "Returns the head-to-head record between the current coaches of two teams. Covers only games during both coaches' tenures — ignores results under different coaches."

### 5. [CODE] Update `agent/prompt.py`

- Amend step 3 (HEAD-TO-HEAD):
  "3. HEAD-TO-HEAD — Check both the team H2H record AND the coaching matchup record. A team's record under a different coach is misleading — focus on the current coaches' records against each other. Note if one coach has a dominant record or if the losing coach has recently adjusted."

### 6. [CODE] CDK updates

- Grant agent Lambda continued read access to `results` table (already granted)
- No new tables needed if using the compute-from-results approach
- If using a cached `coach_matchups` table: add table + update script

## Cost

- Zero additional AWS cost — computes from existing `results` table data
- No new external API calls
- `COACH_MAP` is maintained manually (~10 minutes per season)

## Risks

- **Coach map staleness:** If a mid-season coaching change isn't updated in `COACH_MAP`, matchup records will be wrong. Mitigate: set up a manual reminder when NRL coaching changes are announced.
- **Small sample sizes:** New coaches may have <5 games against a specific opponent. Return the data but flag low confidence.
- **Caretaker coaches:** Interim coaches (e.g. assistant stepping in for 2-3 weeks) complicate the mapping. Simplify: ignore stints <4 games.

## Definition of Done

- [ ] `COACH_MAP` covers all 17 NRL teams' current coaches
- [ ] `get_coaching_matchup` returns coach-vs-coach records from results data
- [ ] Agent references coaching matchup in reasoning alongside team H2H
- [ ] Prompt updated to distinguish team H2H from coaching matchup
- [ ] Results filtered to current coaches' tenures only
