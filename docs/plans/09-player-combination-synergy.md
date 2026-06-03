# Plan: Player Combination Synergy (Phase 7F)

## Goal

Track how often key player combinations (especially spine pairings) have played together, and their win rate as a unit. Flag when a team fields a spine combination with <5 games together — that's a hidden vulnerability invisible in individual player quality assessments.

## Why This Matters

NRL is a team sport where combinations matter more than individual talent:

- **Halfback + Hooker:** The playmaking axis. A new hooker disrupts service speed, timing of short passes, and kicking game setup. Even an elite hooker needs 3-4 games to build timing with a halfback.
- **Fullback + Halves:** Fullback's positioning on kick returns and in the line depends on anticipating where the halves will put the ball. A fill-in fullback disrupts the entire back-three structure.
- **Halves pairing (6+7):** Five-eighth and halfback need telepathic understanding. When one is replaced, the other's effectiveness drops measurably.
- **Hooker + Props:** Dummy-half running game depends on props setting up quick play-the-balls. A new front-row pairing changes the ruck speed.

Current analysis treats each player independently: "Player X is out, replaced by Player Y who is also good." But the question isn't whether Y is good — it's whether Y has ever played with the existing halves/hooker/fullback.

## Data Model

### Computed from existing data (no new table initially)

The team sheet data already in the `teams` table contains the full 1-17 for each match. By querying historical team sheets, we can build combination profiles on the fly.

### Future: `combinations` cache table

If computation becomes too slow, pre-compute and cache:

| Field | Type | Description |
|-------|------|-------------|
| `combinationId` (PK) | String | Sorted player slugs, e.g. `cleary-edwards-luai` |
| `season` (SK) | String | Season year |
| `players` | List | Player names |
| `positions` | List | Positions (e.g. [1, 6, 7]) |
| `team` | String | Team nickname |
| `games_together` | Number | Count of games this combination started |
| `wins` | Number | Wins with this combination |
| `win_rate` | Number | 0-1 |
| `avg_margin` | Number | Average margin (positive = winning) |
| `updatedAt` | String | ISO timestamp |

## Spine Positions

Focus on the four spine positions — the most impactful combinations:

| Position | Number | Why it matters |
|----------|--------|----------------|
| Fullback | 1 | Last line of defence, kick return, line support |
| Five-eighth | 6 | First receiver, creative plays, left-side attack |
| Halfback | 7 | Game manager, kicking, right-side attack |
| Hooker | 9 | Service from dummy-half, ruck control, short kicking |

Key combinations to track:
- **Full spine (1-6-7-9):** How many games have all four started together?
- **Halves pairing (6-7):** Most critical combination
- **Playmaking triangle (6-7-9):** Covers the three key ball distributors
- **Fullback + halves (1-6-7):** Back-three structure

## Implementation Steps

### 1. [TEST] Write `tests/agent/test_tool_spine_synergy.py`

- Test `get_spine_synergy(match_id, round_number)` returns combination data for both teams
- Test games-together count from historical team sheets
- Test win rate calculation
- Test flagging when combination has <5 games together
- Test handling of mid-season player changes (new signing, returning from injury)

### 2. [CODE] Create `agent/tools/spine_synergy.py`

```python
def get_spine_synergy(
    match_id: str,
    round_number: int,
    table=None,
    results_table=None,
) -> dict:
    """Analyse spine combination experience for both teams in a match."""
```

Logic:
1. Get current team sheets for the match (positions 1, 6, 7, 9 for each team)
2. Query historical team sheets for the same team this season
3. For each historical game, check if the same players were in the same spine positions
4. Count games together, cross-reference with results for win rate
5. Flag combinations with <5 games together

Returns:
```python
{
    "home_team": {
        "team": "Panthers",
        "spine": {
            "fullback": "Dylan Edwards",
            "five_eighth": "Jarome Luai",
            "halfback": "Nathan Cleary",
            "hooker": "Api Koroisau"
        },
        "full_spine_games_together": 18,
        "full_spine_win_rate": 0.78,
        "halves_games_together": 45,
        "halves_win_rate": 0.73,
        "is_established": True,
        "flags": []
    },
    "away_team": {
        "team": "Bulldogs",
        "spine": {
            "fullback": "Connor Tracey",
            "five_eighth": "Matt Burton",
            "halfback": "Drew Hutchison",
            "hooker": "Reed Mahoney"
        },
        "full_spine_games_together": 3,
        "full_spine_win_rate": 0.33,
        "halves_games_together": 6,
        "halves_win_rate": 0.50,
        "is_established": False,
        "flags": [
            "New spine combination: Tracey-Burton-Hutchison-Mahoney have only 3 games together",
            "Halves pairing Burton-Hutchison is relatively new (6 games)"
        ]
    },
    "synergy_edge": "Panthers have a significant spine synergy advantage (18 games together vs 3)"
}
```

### 3. [CODE] Register tool in `agent/graph.py`

- Add `get_spine_synergy` to `_TOOL_DEFINITIONS` and `_execute_tool`
- Description: "Analyses how many games each team's spine (fullback, five-eighth, halfback, hooker) have played together this season. Flags new combinations with <5 games together as a vulnerability."

### 4. [CODE] Update `agent/prompt.py`

- Amend step 1 (TEAM SHEET QUALITY):
  "1. TEAM SHEET QUALITY — Retrieve both team sheets AND spine synergy data. A team may have quality individuals but a new combination in the spine is a significant risk factor. Pay special attention to halves pairings with <5 games together — timing and understanding take time to develop."

### 5. [CODE] CDK updates

- Agent Lambda already has read access to `teams` and `results` tables
- No new tables for the compute-on-demand approach
- If caching: add `combinations` table

## Performance Considerations

Computing combinations requires scanning historical team sheets for the season (~12 rounds × 16 teams = ~200 records). This is a full table scan with filter — acceptable for a Lambda but could be slow if the table grows.

**Optimisation path:**
1. Start with compute-on-demand (scan + filter)
2. If too slow (>3s), add a GSI on the `teams` table for team+round lookups
3. If still too slow, pre-compute combinations weekly into a cache table

## Historical Data Requirement

This feature needs team sheet data from previous rounds. The `teams` table should already have this from the orchestrator's weekly scrapes. Verify coverage:

```bash
aws dynamodb scan --table-name teams \
  --filter-expression "begins_with(teamId, :ts)" \
  --expression-attribute-values '{":ts": {"S": "round-"}}' \
  --select COUNT --region ap-southeast-2
```

If historical team sheets are sparse, backfill from NRL.com match centre pages for the current season.

## Cost

- Zero additional AWS cost for compute-on-demand approach
- ~200 DynamoDB reads per match (historical team sheet scan) — well within free tier
- No new external API calls

## Risks

- **Team sheet data gaps:** If historical team sheets aren't in the `teams` table, combinations can't be computed. May need a backfill script.
- **Position number changes:** Some coaches use unconventional numbering (e.g. lock wearing 7, halfback wearing 13 in jersey-swap games). The NRL data should have actual positions, not just jersey numbers — verify.
- **Interchange/HIA:** Players who start on the bench but move into spine positions during the game aren't captured by the starting team sheet. This is a limitation we accept — starting combinations are what matters for pre-match prediction.
- **Named vs actual:** Sometimes a player is named at 7 but plays at 6 on game day. Pre-match team sheets are the best we have.

## Definition of Done

- [ ] `get_spine_synergy` returns combination data for both teams
- [ ] Games-together count is accurate against historical team sheets
- [ ] Combinations with <5 games together are flagged
- [ ] Agent references spine synergy in reasoning, especially when one team has a new combination
- [ ] Prompt updated to emphasise combination experience over individual quality
- [ ] Performance acceptable (<3s per tool call)
