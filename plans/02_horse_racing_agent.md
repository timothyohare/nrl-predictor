# Plan: Horse Racing Multi-Agent Predictor

## Why horse racing fits the model better than NRL for rapid iteration

| Property | NRL | Horse Racing |
|---|---|---|
| Predictions per week | 8 | 200-400 (6-8 races x 4-6 meetings/day) |
| Results latency | 80 min game | ~2 min after race |
| Season | Feb-Oct | Year-round |
| Calibration cycle | Weekly | Daily |
| Input freshness | Team lists drop Tue | Barrier draws + scratchings up to 30min pre-race |
| Prediction granularity | Match winner + margin | Ranked finishing order + win probability |

Racing gives 50x the feedback loops of NRL. A model that is wrong can be identified,
diagnosed, and corrected within the same day. This is the single strongest reason to build
racing before any other alternative domain.

---

## Goal

A multi-agent LangGraph system that produces a ranked finishing order and win probability
for each horse in a race, combining three specialist analysis streams: form, track conditions,
and market intelligence. A judge agent synthesises the three into a final ranked output.

**NOT** a betting recommendation engine. The goal is accurate probability estimation — the
same goal as the NRL predictor. Comparison with actual betting markets is a calibration tool,
not an output. Odds data is joined post-prediction only.

---

## Stack

- **Language**: Python 3.12
- **Agent framework**: LangGraph 0.2+ (parallel node fan-out)
- **LLM SDK**: langchain-anthropic
- **Infra**: AWS Lambda, EventBridge cron, DynamoDB, S3
- **IaC**: AWS CDK Python
- **Tests**: pytest + moto

---

## Data sources

### Primary sources (free / low-cost)

| Source | Data | Access method |
|---|---|---|
| Racing.com | Race cards, fields, barrier draws, scratchings, form guide, results | Public API (undocumented but stable) |
| racing.com/form-guide | Last 10 starts per horse — sectionals, class, prize money | HTML scrape |
| TAB.com.au | Fixed odds, fluctuations, market % | Public page scrape or TAB API |
| Sky Racing / Racing Post | Jockey/trainer stats, track bias notes | HTML scrape |
| BOM | Track weather — rain, temperature | Reuse existing BOM scraper from NRL project |
| State racing authority sites | Track condition rating (Good 4, Soft 7, etc.) | HTML scrape |

### Racing.com API endpoints (to be confirmed in spike)

Expected endpoints based on public network traffic:
- GET /api/racing/race-card/{date}/{meeting}/{race} — field, barriers, weights
- GET /api/racing/form/{horse-id} — last 10 starts with sectionals
- GET /api/racing/results/{date}/{meeting}/{race} — official result
- GET /api/racing/track-conditions/{meeting-id} — track rating + rail position

### Spike required

Before building: write a throwaway script that:
1. Pulls a race card for a single meeting
2. Pulls form for each runner
3. Scrapes TAB fixed odds for the same race
4. Checks how far in advance barrier draws are published (target: 24h before)
5. Confirms result API has official margins + settling time

---

## Agent architecture

```
  race_id
     |
     v
 [Race Context Loader]        pull race card, barrier draw, track conditions
     |
     +----------+----------+
     |          |          |
     v          v          v
  [Form      [Track &   [Market
  Analyst]   Conditions] Intelligence]
     |          |          |
     +----------+----------+
                |
                v
           [Judge]           synthesise three streams into ranked field
                |
                v
           [Output]          write to DynamoDB race_predictions table
```

All three analyst nodes run in parallel — LangGraph supports this via `add_node` + branching.

### LangGraph state

```python
class RacePredictionState(TypedDict):
    race_id: str
    meeting: MeetingContext         # venue, date, track condition, rail, weather
    field: list[HorseEntry]         # all runners with barrier, weight, jockey, trainer
    form_analysis: FormAnalysis     # from Form Analyst
    conditions_analysis: ConditionsAnalysis   # from Track & Conditions Analyst
    market_analysis: MarketAnalysis # from Market Intelligence Analyst
    final_ranking: list[RankedRunner]
    win_probabilities: dict[str, float]
    agent_trace: list[TraceEntry]
```

Parallel fan-out pattern in LangGraph:

```python
graph.add_node("loader",     race_context_loader)
graph.add_node("form",       form_analyst_node)
graph.add_node("conditions", conditions_analyst_node)
graph.add_node("market",     market_analyst_node)
graph.add_node("judge",      judge_node)

graph.set_entry_point("loader")
# loader fans out to all three analysts simultaneously
graph.add_edge("loader",     "form")
graph.add_edge("loader",     "conditions")
graph.add_edge("loader",     "market")
# all three feed into judge
graph.add_edge("form",       "judge")
graph.add_edge("conditions", "judge")
graph.add_edge("market",     "judge")
graph.add_edge("judge",      END)
```

---

## Node 1: Race Context Loader (no LLM)

Pure Python — scrapes and assembles all data for the race. No LLM needed.

**Outputs to state**:
- meeting: venue name, track condition (Good 4 / Soft 7 / Heavy 10), rail position,
  temperature, precipitation forecast
- field: for each runner — name, barrier, weight carried, jockey name, trainer name,
  horse ID (for form lookups), last start finish, class rating

**Scheduling**: runs 2h before each race. Barrier draws typically published ~1h before.

---

## Node 2: Form Analyst

**Model**: claude-haiku-4-5-20251001

**Task**: Assess each horse's form. Output a ranked shortlist of contenders.

**Tools**:

```python
@tool
def get_horse_form(horse_id: str, num_starts: int = 10) -> HorseFormHistory:
    """Last N starts: finish position, winning distance, class, surface, sectionals."""

@tool
def get_jockey_stats(jockey_id: str, track: str = None) -> JockeyStats:
    """Win%, place%, strike rate at this track/distance."""

@tool
def get_trainer_stats(trainer_id: str, track: str = None) -> TrainerStats:
    """Trainer win% at this track and at this time of season."""

@tool
def get_horse_class_history(horse_id: str) -> ClassHistory:
    """Rising/falling in class. Class of opposition in recent starts."""
```

**Analysis dimensions**:
1. **Recency**: Last-start winner, placed, or disappointing — with allowance for excuses
2. **Class assessment**: Is this horse rising in class, dropping, or at its level?
3. **Jockey booking**: Has a top jockey been engaged? (signals trainer confidence)
4. **Distance**: Win/place record at this exact distance
5. **Track**: Record at this track (some horses genuinely prefer certain surfaces)
6. **Sectional times**: Early speed vs late kick — useful for barrier/track bias context

**Output**:

```python
class FormAnalysis(BaseModel):
    contenders: list[FormContender]   # ranked by form assessment
    form_standout: str | None         # horse name if one is clearly superior
    form_notes: str                   # 200-300 words

class FormContender(BaseModel):
    horse_name: str
    form_rating: float           # 0-100 internal score
    form_summary: str            # one-line reason
    concerns: str | None         # notable risks (class rise, long lay-off, etc.)
```

---

## Node 3: Track & Conditions Specialist

**Model**: claude-haiku-4-5-20251001

**Task**: Identify which horses are advantaged or disadvantaged by today's specific track
conditions, barrier, and rail position.

**Tools**:

```python
@tool
def get_track_condition_record(horse_id: str) -> TrackConditionRecord:
    """Win/place record on Good, Soft, Heavy going."""

@tool
def get_barrier_stats(barrier: int, track: str, distance: str) -> BarrierStats:
    """Historical win% from this barrier at this track/distance."""

@tool
def get_rail_position_bias(track: str, rail: str) -> RailBias:
    """Whether inside/outside barriers have statistical advantage given rail position."""

@tool
def get_weight_impact(weight_carried: float, horse_id: str) -> WeightAssessment:
    """Weight relative to horse's last starts and typical carry."""
```

**Analysis dimensions**:
1. **Going preference**: Horses that love/hate soft or heavy tracks
2. **Barrier advantage/disadvantage**: Statistical barrier bias at this track + distance
3. **Rail position**: How the rail affects whether wide runs or tight lines are favoured
4. **Weight**: Impost changes from last start — significant if +3kg or more
5. **Distance**: First-up at this distance, or proven at it?

**Output**:

```python
class ConditionsAnalysis(BaseModel):
    conditions_winners: list[str]   # horses advantaged by today's conditions
    conditions_losers: list[str]    # horses disadvantaged
    barrier_advantaged: list[str]   # horses with statistical barrier edge
    track_notes: str                # 150-200 words
```

---

## Node 4: Market Intelligence Analyst

**Model**: claude-haiku-4-5-20251001

**Task**: Interpret the betting market. Identify smart money, overlays, and market
anomalies that suggest public money is distorting prices.

**Important**: This node's output is a market interpretation signal — it feeds the judge
but does NOT override form or conditions. The goal is calibration, not following markets.

**Tools**:

```python
@tool
def get_current_odds(race_id: str) -> RaceOdds:
    """Fixed odds from TAB for all runners."""

@tool
def get_odds_movement(race_id: str) -> OddsMovement:
    """Opening price vs current price — firmers and drifters."""

@tool
def get_market_percentage(race_id: str) -> float:
    """Sum of implied probabilities. >100% = overround."""

@tool
def get_bookmaker_consensus(race_id: str) -> ConsensusOdds:
    """Average across multiple bookmakers (if available)."""
```

**Analysis dimensions**:
1. **Strong firmer**: Price has shortened significantly since opening — often indicates
   informed money, especially for lesser-known horses
2. **Drifter**: Price has blown out — may indicate scratchings, stable news, or
   market has reassessed
3. **Overlay detection**: Horses whose form/conditions analysis suggests they should
   be shorter than their current price
4. **Market favourite profile**: Is the market favourite consistent with form reading,
   or is it a public/media darling?

**Output**:

```python
class MarketAnalysis(BaseModel):
    market_favourite: str
    strong_firmers: list[str]      # horses with >20% price shortening
    notable_drifters: list[str]    # horses with >30% price lengthening
    market_confidence: str         # HIGH if favourite is well-supported, LOW if erratic
    market_notes: str              # 100-150 words
    overlay_candidates: list[str]  # horses where form > market price suggests
```

---

## Node 5: Synthesis Judge

**Model**: claude-sonnet-4-6 (upgrade from Haiku — synthesis is the hardest reasoning step)

**Task**: Read all three analysis streams and produce the final ranked finishing order.

**Decision framework**:
- Weight the three streams: Form (50%), Conditions (30%), Market (20%) as a starting point
- Conditions weight increases to 40% when track is Soft 7+ or Heavy
- Market weight increases to 30% when market confidence is HIGH and a strong firmer
  is present (strong firmers are the highest-signal market movement)
- Override market weight down to 10% when market percentage > 115% (saturated overround
  indicates a distorted market, often dominated by public money on one runner)

**Output**:

```python
class RankedRunner(BaseModel):
    position: int           # 1 = predicted winner
    horse_name: str
    win_probability: float  # must sum to ~1.0 across field
    place_probability: float
    rationale: str          # one-line reason for this ranking

class JudgeOutput(BaseModel):
    ranked_field: list[RankedRunner]
    predicted_winner: str
    predicted_exacta: tuple[str, str]   # 1st and 2nd
    judge_rationale: str                 # 200-300 words
    confidence: Literal["LOW", "MEDIUM", "HIGH"]
    key_factors: list[str]               # 2-4 items for display
```

---

## DynamoDB tables

### race_cards table

PK: `raceId` (format: `{date}-{track}-{race_num}`, e.g. `2026-06-07-flemington-r4`)
SK: `scrapedAt`
- meeting, track_condition, rail_position, weather
- field (list of runners with barrier, weight, jockey, trainer)

### race_predictions table

PK: `raceId`, SK: `generatedAt`
- ranked_field
- predicted_winner
- predicted_exacta
- confidence
- key_factors
- judge_rationale
- form_analysis, conditions_analysis, market_analysis (stored for audit)
- agent_trace
- prompt_version

### race_results table

PK: `raceId`, SK: `resultAt`
- official finish order
- margins
- winning time
- dividends (win, place, exacta)

### race_metrics table

PK: `period` (e.g. `2026-06`, `2026-season`)
SK: `metricName`
- pick_rate (predicted winner % correct)
- top3_accuracy (winner in top 3 predictions %)
- exacta_accuracy
- confidence_calibration (same Brier score approach as NRL)
- market_comparison (our accuracy vs TAB favourite %)

---

## Scoring + calibration

Results are available ~2 minutes after each race. The scoring Lambda:

1. Reads the official result from Racing.com API
2. Scores prediction: win (1.0), placed (0.5), unplaced (0.0)
3. Calculates Brier score for win probability estimates
4. Writes to race_results and updates race_metrics
5. Async-invokes retrospective Lambda for post-race analysis

The cadence allows for same-day calibration. If the Form Analyst is systematically
wrong on Soft tracks, this shows up in metrics within days, not weeks.

---

## Scheduling

```
08:00 AEST  Race card scraper runs — pulls all meetings for the day
08:30 AEST  Barrier draw scraper runs (published at ~08:15)
09:00 AEST  Prediction agent runs for all morning races (race 1 typically 11:30)
12:00 AEST  Update predictions for afternoon races (scratchings, late changes)
14:00 AEST  Update predictions for evening races
+2min/race  Scoring Lambda fires after each result
21:00 AEST  Daily metrics aggregation
```

---

## Front end

Reuse the same Next.js + Tailwind + Amplify pattern. Each race card shows:

- Predicted winner + win probability
- Top 3 ranked field with probabilities
- Key factors (form_notes, conditions notes)
- Confidence badge
- Post-race: actual result + accuracy badge

---

## Estimated build time

| Phase | Effort |
|---|---|
| Racing data spike (Racing.com + TAB API) | 1-2 days |
| Data models + DynamoDB tables | 0.5 day |
| Race card scraper + results scraper | 1-2 days |
| Form Analyst node + tools | 1.5 days |
| Track & Conditions node + tools | 1 day |
| Market Intelligence node + tools | 1 day |
| Judge synthesis node | 1 day |
| Graph wiring + Lambda handler | 0.5 day |
| Scoring + metrics | 1 day |
| CDK infra | 0.5 day |
| Tests (TDD throughout) | included above |
| Front end (reuse template) | 1 day |

Total: ~12-14 dev days. Fast calibration means the model improves quickly once deployed.

---

## Key risks

1. **Racing.com API stability**: The API is undocumented — endpoints may change. Mitigation:
   cache aggressively in S3, build retry + fallback to HTML scrape.

2. **Scratchings timing**: Horses can be scratched within 30min of a race. Mitigation:
   re-run predictions after the final field is confirmed (typically 30min before jump).

3. **Barrier draw timing**: Some tracks publish late. Mitigation: prediction runs without
   barrier analysis if not available, adds it on re-run.

4. **Model overfit to market**: If Market Intelligence node carries too much weight,
   predictions just mirror TAB. Keep market weight capped at 20-30% in judge prompt.
