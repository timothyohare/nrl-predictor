# Plan: Momentum Decay Weighting (Phase 7C)

## Goal

Replace the agent's flat "last 4-6 games" form assessment with exponentially decay-weighted form that captures momentum direction. A team that won 3 then lost 3 is fundamentally different from a team that lost 3 then won 3 — the current tool treats them identically.

## Why This Matters

The existing `get_recent_form` tool returns the last N results sorted by date. The agent sees "3 wins, 3 losses in last 6" for both teams above. But:
- **Rising team (L L L W W W):** Momentum, confidence building, possibly found a winning formula
- **Falling team (W W W L L L):** Losing confidence, possibly injuries compounding, opposition has figured them out

NRL punters and analysts heavily weight "what have you done lately" — a team's last 2-3 games are far more predictive than games 5-6 weeks ago. Academic sports prediction research supports exponential decay with a half-life of 2-3 games.

## Data Model

No new DynamoDB tables needed. This enhances the existing `get_recent_form` tool response with computed metrics.

## Computed Metrics

For each team's recent form, calculate:

| Metric | Formula | Description |
|--------|---------|-------------|
| `weighted_win_rate` | Sum(w_i × result_i) / Sum(w_i) where w_i = decay^i | Win rate weighted by recency |
| `momentum_direction` | `rising` / `falling` / `stable` | Based on gradient of weighted results |
| `momentum_score` | Float -1.0 to +1.0 | Positive = improving, negative = declining |
| `streak` | `W3` / `L2` / etc. | Current streak |
| `weighted_points_for` | Decay-weighted average points scored | Recent scoring trend |
| `weighted_points_against` | Decay-weighted average points conceded | Recent defensive trend |
| `form_string` | `W W L W W W` (most recent first) | Quick visual |

### Decay Function

```python
weight = decay_factor ** games_ago
# decay_factor = 0.7 → half-life ≈ 2 games
# Game 0 (most recent): weight = 1.0
# Game 1: weight = 0.7
# Game 2: weight = 0.49
# Game 3: weight = 0.34
# Game 4: weight = 0.24
# Game 5: weight = 0.17
```

## Implementation Steps

### 1. [TEST] Write `tests/agent/test_momentum.py`

- Test decay weighting calculation with known inputs
- Test momentum direction classification:
  - `[W, W, W, L, L, L]` → `rising` (recent wins)
  - `[L, L, L, W, W, W]` → `falling` (recent losses)
  - `[W, L, W, L, W, L]` → `stable`
- Test momentum score is in range [-1.0, 1.0]
- Test edge cases: 0 games, 1 game, all wins, all losses
- Test weighted points for/against

### 2. [CODE] Create `agent/tools/momentum.py`

- `calculate_momentum(results: list[dict], decay_factor: float = 0.7) -> dict`
- Pure function — takes sorted results, returns computed metrics
- No DynamoDB dependency — operates on the output of `get_recent_form`

### 3. [CODE] Update `agent/tools/recent_form.py`

- After fetching raw results, call `calculate_momentum()` and include metrics in the response
- Return structure changes from `list[dict]` to `dict` with `results` + `momentum` keys:
  ```python
  {
      "results": [...],  # existing raw results
      "momentum": {
          "weighted_win_rate": 0.72,
          "momentum_direction": "rising",
          "momentum_score": 0.35,
          "streak": "W3",
          "weighted_points_for": 24.5,
          "weighted_points_against": 18.2,
          "form_string": "W W W L L W",
      }
  }
  ```

### 4. [TEST] Update `tests/agent/test_tool_get_recent_form.py`

- Verify existing tests still pass with new response shape
- Add test for momentum metrics in response

### 5. [CODE] Update `agent/prompt.py`

- Amend step 2 (RECENT FORM):
  "2. RECENT FORM — Assess each team's momentum using the weighted form data. Pay attention to momentum direction (rising/falling/stable) and the weighted win rate rather than raw win count. A team on a 3-game winning streak is more dangerous than their season record suggests."

### 6. [CODE] Update tool description in `agent/graph.py`

- Update `get_recent_form` description to mention momentum metrics:
  "Returns the last n match results for a team with momentum analysis: weighted win rate, momentum direction (rising/falling/stable), current streak, and weighted scoring trends."

## Example

**Panthers recent form:** W(24-18), W(30-12), L(14-20), W(22-16), L(10-28), L(8-24)

| Game | Result | Points For | Points Against | Weight (0.7 decay) |
|------|--------|-----------|----------------|---------------------|
| 0 (most recent) | W | 24 | 18 | 1.000 |
| 1 | W | 30 | 12 | 0.700 |
| 2 | L | 14 | 20 | 0.490 |
| 3 | W | 22 | 16 | 0.343 |
| 4 | L | 10 | 28 | 0.240 |
| 5 | L | 8 | 24 | 0.168 |

- **Weighted win rate:** (1.0 + 0.7 + 0 + 0.343 + 0 + 0) / (1.0 + 0.7 + 0.49 + 0.343 + 0.24 + 0.168) = 2.043 / 2.941 = **0.695**
- **Raw win rate:** 3/6 = 0.500
- **Momentum direction:** `rising` (recent games trending wins)
- **Streak:** W2
- **Weighted PF:** (24×1.0 + 30×0.7 + 14×0.49 + 22×0.343 + 10×0.24 + 8×0.168) / 2.941 = **22.1**
- **Weighted PA:** (18×1.0 + 12×0.7 + 20×0.49 + 16×0.343 + 28×0.24 + 24×0.168) / 2.941 = **17.3**

The weighted view tells a very different story from "3 wins, 3 losses": Panthers are improving, scoring well recently, and defending better.

## Cost

- Zero additional AWS cost — this is pure computation on existing data
- No new API calls, tables, or Lambda functions

## Risks

- **Decay factor sensitivity:** 0.7 is a reasonable default but the optimal value is unknown. The prompt tournament (Phase 9) could test different decay factors as a dimension.
- **Small sample at season start:** Early rounds have <6 games of history. Handle gracefully — use whatever's available, flag low confidence.
- **Agent interpretation:** The agent might ignore momentum metrics if the prompt doesn't emphasise them enough. Monitor via retrospectives.

## Definition of Done

- [ ] `calculate_momentum()` produces correct weighted metrics
- [ ] `get_recent_form` response includes momentum analysis
- [ ] Agent references momentum direction and weighted form in reasoning
- [ ] Existing form-related tests still pass
- [ ] Prompt updated to emphasise momentum over raw win count
