# Plan: NRL Predictor v2 — LangGraph Multi-Agent System

## Goal

Rebuild the NRL predictor as a proper multi-agent LangGraph application. The current system
is a single ReAct agent calling tools. v2 makes prediction quality an emergent property of
multiple specialised agents cross-checking each other: a router that decides how much
analytical horsepower a match deserves, a primary predictor, a challenger that argues the
opposite case, a synthesis judge that weighs the debate, and an extended predictor that adds
first-try scorer, margin bracket, and key player prop predictions.

Reuse all existing scrapers, DynamoDB tables, API keys, and Amplify front end. Only the
agent layer changes.

---

## Why LangGraph over the current ReAct loop

| Current (ReAct) | v2 (LangGraph) |
|---|---|
| Single agent loops until it calls `submit_prediction` | Explicit state machine — each node has a defined role |
| No adversarial check on reasoning | Challenger reduces overconfidence |
| One model for all matches | Router dynamically selects cost/quality tier |
| No first-try scorer or player props | Extended Predictor node adds these |
| Reasoning is implicit in the tool call log | Full agent trace stored and auditable |

---

## Stack

- **Language**: Python 3.12
- **Agent framework**: LangGraph 0.2+ (StateGraph with typed state)
- **LLM SDK**: `langchain-anthropic` (Claude models)
- **Tools**: LangChain `@tool` wrappers around existing DynamoDB-backed functions
- **Infra**: AWS Lambda, EventBridge cron, DynamoDB, S3 (same as v1)
- **IaC**: AWS CDK Python
- **Tests**: pytest + moto (same pattern as v1)
- **Front end**: Existing Next.js app with minor schema additions

---

## Data sources (unchanged from v1)

| Source | What it provides |
|---|---|
| scrapers/nrl/draw.py | Fixture, venue, kick-off time |
| scrapers/nrl/team_sheets.py | Starting 13 + bench |
| scrapers/nrl/ladder.py | Season standings |
| scrapers/weather/ | BOM hourly + Open-Meteo fallback |
| scrapers/articles/ | RSS injury news (Haiku extraction) |
| scrapers/odds/ | Market odds — comparison only, never agent input |

---

## Agent architecture

```
  match_id
     |
     v
 [Router]                    classify difficulty, select model tier
     |
     v
 [Primary Predictor]         Haiku (EASY) or Sonnet (CONTESTED/COMPLEX)
     |                       uses tools: team_sheet, form, H2H, ladder,
     |                       weather, injuries, web_search
     v
 [Challenger]                Sonnet — always argues the opposite case
     |
     v
 [Synthesis Judge]           Sonnet — weighs primary vs challenger
     |                       produces final prediction + adjusted confidence
     v
 [Extended Predictor]        Haiku — first try scorer, margin bracket, props
     |
     v
 [Output]                    write to DynamoDB predictions table
```

### LangGraph state (TypedDict)

```python
class MatchPredictionState(TypedDict):
    match_id: str
    match_context: MatchContext        # draw + team sheets + ladder + weather + news
    difficulty: str                    # EASY / CONTESTED / COMPLEX
    difficulty_rationale: str
    primary_model: str
    primary_prediction: PrimaryPrediction
    challenge: Challenge               # challenger's counter-argument
    final_prediction: FinalPrediction  # judge's synthesis
    extended: ExtendedPrediction       # first try scorer, margin bracket
    agent_trace: list[TraceEntry]      # full audit log
```

Graph compiled at Lambda cold-start:

```python
graph = StateGraph(MatchPredictionState)
graph.add_node("router",    router_node)
graph.add_node("primary",   primary_node)
graph.add_node("challenger", challenger_node)
graph.add_node("judge",     judge_node)
graph.add_node("extended",  extended_node)
graph.set_entry_point("router")
graph.add_edge("router",     "primary")
graph.add_edge("primary",    "challenger")
graph.add_edge("challenger", "judge")
graph.add_edge("judge",      "extended")
graph.add_edge("extended",   END)
app = graph.compile()
```

---

## Node 1: Difficulty Router

**Model**: claude-haiku-4-5-20251001 (cheap classification task)

**Task**: Classify the match and select the appropriate model tier.

Difficulty rules:
- EASY: betting spread > 12pts AND no spine injuries AND H2H favours favourite 4+/5
- CONTESTED: spread 6-12pts OR one spine injury OR close H2H OR venue disadvantage
- COMPLEX: spread < 6pts OR multiple spine injuries OR finals/elimination match
  OR local derby OR away team on strong form vs home side slumping

**Output** (Pydantic structured output):

```python
class RouterOutput(BaseModel):
    difficulty: Literal["EASY", "CONTESTED", "COMPLEX"]
    rationale: str
    primary_model: str    # haiku or sonnet
    challenger_model: str # always sonnet
```

Cost note: In a typical round of 8 matches — ~3 EASY (Haiku only), 4 CONTESTED (Sonnet),
1 COMPLEX (Sonnet). Routing saves ~55% token cost vs running Sonnet for every match.

---

## Node 2: Primary Predictor

**Model**: router-selected (Haiku or Sonnet)

**Tools** (LangChain @tool wrappers, same DynamoDB logic as v1):

- get_team_sheet(match_id) — starting 13 + bench
- get_form_guide(team_id, num_games=5) — last N results + points diff
- get_head_to_head(home_team, away_team) — H2H last 10, home/away splits
- get_ladder() — season standings
- get_weather(venue, kickoff_utc) — match-day forecast
- get_injury_news(team_id) — extracted injury alerts
- get_venue_profile(venue) — home advantage stats, surface
- get_coaching_matchup(home_coach, away_coach) — coaching H2H
- web_search(query) — referee, late-breaking news

**Chain-of-thought steps** (enforced in system prompt):
1. Team sheets — who is and isn't playing
2. Form + momentum — last 5, trajectory
3. H2H + coaching matchup
4. Home/away advantage
5. Venue profile + weather impact
6. Injury news — severity weighting
7. Verdict

**Output schema** (same as v1 prediction schema):

```python
class PrimaryPrediction(BaseModel):
    predicted_winner: str
    predicted_margin: int
    confidence: Literal["LOW", "MEDIUM", "HIGH"]
    key_factors: list[str]    # 2-4 items
    reasoning: str            # 200-400 words
```

---

## Node 3: Challenger

**Model**: claude-sonnet-4-6 (always — challenger needs strong reasoning)

**Task**: Given the primary prediction, argue the opposing case as forcefully as possible.
The challenger is NOT trying to be right; it is trying to find holes in the primary's logic.

**System prompt framing**:

```
You are a contrarian NRL analyst. You have been given a match prediction.
Your job is to argue AGAINST it — find the strongest possible case for the other team.
Look for: overlooked injuries, home ground narratives the primary missed, form anomalies,
referee tendencies, coaching X-factors, trap game signals.
You must produce a structured counter-prediction, even if you personally think the
original is correct. Rate the strength of your challenge: WEAK / MODERATE / STRONG.
```

**Output**:

```python
class Challenge(BaseModel):
    counter_winner: str
    counter_margin: int
    challenge_strength: Literal["WEAK", "MODERATE", "STRONG"]
    key_counterpoints: list[str]    # 2-4 items
    challenge_reasoning: str        # 150-300 words
```

A WEAK challenge from a strong primary is a confidence booster for the judge.
A STRONG challenge triggers the judge to downgrade confidence or widen margin uncertainty.

---

## Node 4: Synthesis Judge

**Model**: claude-sonnet-4-6

**Task**: Read both the primary prediction and the challenger. Decide the final prediction.

The judge has access to:
- Primary prediction + reasoning
- Challenger counter-prediction + reasoning
- Challenge strength rating
- Original match context

**Decision rules** (soft — judge uses these as a framework, not hard logic):
- If challenge strength is WEAK: accept primary, possibly upgrade confidence
- If challenge strength is MODERATE: accept primary winner but soften margin by 2-4pts
  and consider whether confidence should drop one tier
- If challenge strength is STRONG: re-evaluate winner, potentially flip if challenger's
  case is more compelling; minimum confidence is LOW

**Output**:

```python
class FinalPrediction(BaseModel):
    predicted_winner: str
    predicted_margin: int
    confidence: Literal["LOW", "MEDIUM", "HIGH"]
    accepted_primary: bool          # did judge side with primary or challenger?
    judge_rationale: str            # 100-200 words — why judge ruled as they did
    key_factors: list[str]          # 2-4 items for front end display
    reasoning: str                  # 200-400 words — full final reasoning
```

---

## Node 5: Extended Predictor

**Model**: claude-haiku-4-5-20251001 (cheap — decorative predictions, not core accuracy)

**Task**: Given the final prediction + team sheets, add player-level predictions.

**Inputs**: final_prediction + team sheets (no tool calls needed, context already in state)

**Output**:

```python
class ExtendedPrediction(BaseModel):
    first_try_scorer: FirstTryPrediction     # top 3 candidates with probabilities
    margin_bracket: str                       # "1-5", "6-12", "13-20", "21+"
    key_player_to_watch: str                  # name + one-line reason
    upset_probability: float                  # 0.0-1.0 for the underdog winning
```

```python
class FirstTryPrediction(BaseModel):
    candidates: list[FirstTryScorerCandidate]  # top 3

class FirstTryScorerCandidate(BaseModel):
    player_name: str
    team: str
    position: str
    probability: float
    rationale: str
```

---

## DynamoDB schema additions

### predictions table (existing, add fields)

New fields added to each prediction item:
- `agent_difficulty` — EASY / CONTESTED / COMPLEX
- `primary_accepted` — bool (did judge side with primary)
- `challenge_strength` — WEAK / MODERATE / STRONG
- `first_try_candidates` — list of top 3 candidates
- `margin_bracket` — string
- `upset_probability` — float
- `agent_trace` — list of trace entries (JSON)

### agent_traces table (new)

Separate table for full trace storage (keeps predictions table lean):

PK: `matchId`, SK: `generatedAt`
- `trace_entries` — full list of tool calls, intermediate outputs per node
- `total_input_tokens` — sum across all nodes
- `total_output_tokens`
- `nodes_used` — list of node names that ran

---

## New prediction output (API response additions)

The `/predictions/{round}` API adds to each match:

```json
{
  "agent_difficulty": "CONTESTED",
  "challenge_strength": "MODERATE",
  "primary_accepted": true,
  "first_try_candidates": [
    {"player_name": "...", "team": "...", "probability": 0.18, "rationale": "..."},
    {"player_name": "...", "team": "...", "probability": 0.14, "rationale": "..."},
    {"player_name": "...", "team": "...", "probability": 0.11, "rationale": "..."}
  ],
  "margin_bracket": "6-12",
  "upset_probability": 0.31
}
```

---

## Lambda architecture

Three Lambdas:

1. **nrl-predictor-v2-orchestrator** — same as v1 orchestrator, fans out per match
2. **nrl-predictor-v2-agent** — runs the full LangGraph StateGraph for one match
3. **nrl-predictor-v2-api** — same API Lambda, updated to join extended fields

The agent Lambda handler:

```python
def lambda_handler(event, context):
    match_id = event["matchId"]
    # Compile the graph (cached at module level after first cold start)
    result = app.invoke({
        "match_id": match_id,
        "match_context": load_match_context(match_id),
        ...
    })
    write_prediction(result["final_prediction"], result["extended"])
    write_trace(result["agent_trace"])
```

---

## Testing strategy

Follows the same TDD pattern as v1:

| Test file | What it tests |
|---|---|
| tests/agent/test_router_node.py | Router classifies difficulty correctly for fixture cases |
| tests/agent/test_primary_node.py | Primary predictor returns valid PrimaryPrediction |
| tests/agent/test_challenger_node.py | Challenger always produces a counter-winner |
| tests/agent/test_judge_node.py | Judge respects challenge_strength rules |
| tests/agent/test_graph_integration.py | Full graph runs end-to-end with mocked LLM |
| tests/agent/test_extended_node.py | Extended predictor returns valid first-try candidates |

Mocking strategy: LangChain supports `FakeListChatModel` for deterministic testing without
hitting the Anthropic API. Integration tests use moto for DynamoDB.

---

## Project structure

```
nrl-predictor-v2/
  agent/
    graph.py                  # StateGraph definition + compile
    nodes/
      router.py               # Difficulty Router node
      primary.py              # Primary Predictor node
      challenger.py           # Challenger node
      judge.py                # Synthesis Judge node
      extended.py             # Extended Predictor node
    tools/
      team_sheet.py           # @tool wrappers (ported from v1)
      form_guide.py
      head_to_head.py
      ladder.py
      weather.py
      injuries.py
      venue_profile.py
      coaching_matchup.py
      web_search.py
    state.py                  # MatchPredictionState + all Pydantic models
    lambda_handler.py         # AWS Lambda entry point
  scrapers/                   # copied verbatim from v1
  orchestrator/               # same fan-out pattern as v1
  api/                        # same API Lambda, updated response schema
  scoring/                    # same scorer + metrics, no changes needed
  retrospective/              # same, no changes needed
  infra/                      # CDK stack, new Lambda + table definitions
  tests/
    agent/
      test_router_node.py
      test_primary_node.py
      test_challenger_node.py
      test_judge_node.py
      test_extended_node.py
      test_graph_integration.py
    ...
```

---

## Migration / shadow mode

Run v2 in parallel with v1 for 2-3 rounds before switching traffic:

1. Deploy v2 agent with a different table prefix (e.g. `v2_predictions`)
2. Orchestrator invokes both v1 and v2 agents per match (v2 staggered +4s)
3. Compare accuracy: router classification vs actual match closeness, judge flip rate,
   challenger strength distribution
4. Once v2 accuracy >= v1 across at least 2 rounds, cut over the API Lambda

---

## Estimated build time

| Phase | Effort |
|---|---|
| Port scrapers + tool wrappers | 1 day — copy and thin-wrap |
| State + Pydantic models | 0.5 day |
| Router + Primary nodes | 1 day |
| Challenger + Judge nodes | 1.5 days |
| Extended Predictor | 0.5 day |
| Graph wiring + Lambda handler | 0.5 day |
| Tests (TDD throughout) | included above |
| CDK infra updates | 0.5 day |
| Shadow mode + calibration | 1-2 rounds (1-2 weeks) |

Total to deploy to shadow: ~5 dev days.
