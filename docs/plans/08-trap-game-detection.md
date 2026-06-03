# Plan: Trap Game Detection (Phase 7E)

## Goal

Build a schedule context tool that identifies "trap game" conditions — situations where a team is likely to underperform despite being the favourite. This targets the hardest-to-predict matches: upsets that look obvious in hindsight but that raw form/H2H data misses.

## Why This Matters

Trap games are a well-documented phenomenon in all professional sports. Common patterns in NRL:

1. **Sandwich games:** Top-4 team plays a bottom-8 team between two marquee fixtures (e.g. Panthers play Knights between Storm and Roosters). The players mentally "look ahead" to next week.

2. **Emotional letdown:** Team coming off a huge win (rivalry match, comeback from 20+ down, finals berth clinched) faces a lower-ranked opponent. Adrenaline crash.

3. **Dead rubber for favourites:** Late-season game where the favourite has already clinched top-4 and has nothing to play for, while the underdog is fighting for survival (must-win for 8th place).

4. **Travel + short turnaround:** Team played Sunday night interstate, flies home Monday, plays Thursday night. The "favourite" tag ignores physical fatigue.

5. **Revenge game (for the underdog):** The underdog lost a close one to this team earlier in the season. They've been stewing on it. Extra motivation that doesn't show in stats.

These patterns are currently invisible to the agent — it sees form, H2H, and team sheets but has no concept of schedule context.

## Data Model

No new DynamoDB table needed. The tool computes trap game indicators from existing data:
- `teams` table (draw data: who plays whom, when)
- `results` table (recent results for emotional context)
- `predictions` table (ladder position for "nothing to play for" detection)

### Trap Game Score

A composite score from 0 (no trap indicators) to 5 (maximum trap risk):

| Indicator | Points | Condition |
|-----------|--------|-----------|
| Sandwich game | +1.5 | Favourite's next opponent is ranked top-4 AND previous opponent was top-4 |
| Emotional letdown | +1.0 | Favourite won last game by 20+ points OR won a rivalry match |
| Dead rubber | +1.5 | Favourite clinched top-4 AND underdog is 7th-10th on the ladder |
| Short turnaround + travel | +1.0 | <6 days since last game AND interstate travel |
| Revenge game | +0.5 | These teams met earlier this season AND current underdog lost by <8 points |

A score of >= 2.0 triggers a "trap game warning" in the tool response.

## Implementation Steps

### 1. [TEST] Write `tests/agent/test_tool_trap_game.py`

- Test each indicator independently with mock data
- Test composite score calculation
- Test that sandwich game detection correctly looks at previous AND next fixtures
- Test edge cases: round 1 (no previous game), round 27 (no next game), byes
- Test that the tool returns a clear explanation of which indicators fired

### 2. [CODE] Create `agent/tools/trap_game.py`

```python
def detect_trap_game(
    match_id: str,
    round_number: int,
    season: int,
    teams_table=None,
    results_table=None,
) -> dict:
    """Analyse schedule context for trap game indicators."""
```

Returns:
```python
{
    "trap_score": 2.5,
    "is_trap_game": True,
    "indicators": [
        {
            "type": "sandwich_game",
            "points": 1.5,
            "detail": "Panthers play Storm next week (2nd) after beating Roosters (3rd) last week"
        },
        {
            "type": "short_turnaround",
            "points": 1.0,
            "detail": "Panthers played Sunday night in Melbourne, now playing Thursday in Sydney"
        }
    ],
    "affected_team": "Panthers",
    "recommendation": "Consider downgrading Panthers confidence. Trap score 2.5/5."
}
```

### 3. [CODE] Register tool in `agent/graph.py`

- Add `detect_trap_game` to `_TOOL_DEFINITIONS` and `_execute_tool`
- Description: "Analyses schedule context to detect trap game conditions: sandwich games between tough opponents, emotional letdowns, dead rubbers, short turnarounds with travel, and revenge games. Returns a trap score (0-5) with explanations."

### 4. [CODE] Update `agent/prompt.py`

- Add a new step between NEWS and VERDICT:
  "6b. TRAP GAME CHECK — Run the trap game detector. If the trap score is >= 2, seriously consider whether the favourite is vulnerable. Trap games are the #1 source of upset predictions that look obvious in hindsight. Even a small trap score should nudge your confidence down."

### 5. [CODE] Helper: get adjacent fixtures

Need a helper to find what each team played last week and plays next week:

```python
def get_adjacent_fixtures(team, round_number, season, teams_table):
    """Returns previous and next fixture for a team."""
    # Query draw data for round_number-1 and round_number+1
    # Return: {prev_opponent, prev_result, next_opponent, next_opponent_rank, days_between}
```

This queries the `teams` table draw entries for adjacent rounds.

### 6. [CODE] CDK updates

- No new tables or Lambdas
- Agent Lambda already has read access to `teams` and `results` tables

## Example: Round 15, Panthers vs Knights

**Context:**
- Panthers (2nd) play Knights (12th) at home — heavy favourites
- Round 14: Panthers beat Storm (1st) in a thriller, 22-20
- Round 16: Panthers play Roosters (3rd) away

**Trap game analysis:**
- Sandwich game: +1.5 (Storm last week, Roosters next week — both top-4)
- Emotional letdown: +1.0 (beat Storm by 2 in a thriller)
- Dead rubber: 0 (both teams have something to play for)
- Short turnaround: 0 (standard 7-day turnaround)
- Revenge: 0 (Knights haven't played Panthers yet this season)

**Trap score: 2.5** — warning triggered.

**Agent might write:** "Despite Panthers' clear superiority on paper, this is a classic trap game (score 2.5/5). They've just beaten Storm in a physical encounter and face Roosters next week — history shows top teams often sleepwalk through these sandwiched fixtures. Downgrading to MEDIUM confidence despite expecting a Panthers win."

## Cost

- Zero additional AWS cost — computes from existing tables
- 2-3 extra DynamoDB reads per match (adjacent round draw data)

## Risks

- **Over-correction:** The agent might become too cautious about favourites if trap game warnings fire too often. Calibrate thresholds so warnings fire on ~15-20% of matches (roughly the upset rate in NRL).
- **Draw data availability:** Adjacent round fixtures might not be in the `teams` table if the draw hasn't been scraped yet (e.g. round N+1 not available early in the week). Handle gracefully — return partial analysis.
- **Bye rounds:** Teams on a bye the previous week don't have a "previous game" for sandwich detection. Skip that indicator.
- **Magic Round / special events:** All games at one venue — travel indicator doesn't apply. Detect and skip.

## Definition of Done

- [ ] Trap game detector identifies all 5 indicator types
- [ ] Composite score correctly weights indicators
- [ ] Agent references trap game analysis in reasoning for flagged matches
- [ ] Warning fires on ~15-20% of matches (calibrate thresholds)
- [ ] Handles edge cases: round 1, round 27, byes, Magic Round
- [ ] Prompt updated with trap game assessment step
