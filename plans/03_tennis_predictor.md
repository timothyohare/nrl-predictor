# Plan: Tennis Tournament Multi-Agent Predictor

## Why tennis fits the model

| Property | NRL | Tennis |
|---|---|---|
| Predictions per week | 8 | 50-200 (grand slams), 20-50 (tour events) |
| Results latency | 80 min game | 1-4 hours per match |
| Season | Feb-Oct | Year-round (March-November ATP/WTA) |
| Calibration cycle | Weekly | Daily during events |
| Data richness | Team-based, complex | Player-level, granular serve/return stats |
| Upset frequency | ~30% | ~35% — higher variance, more interesting to model |
| International interest | AU-heavy | Global — potential to expand audience |

Tennis has extremely clean, granular historical data (ATP/WTA maintain exhaustive stats),
daily matches during events, and results within hours. It is ideal for rapid iteration.

During the four grand slams alone (Australian Open, French Open, Wimbledon, US Open) there
are 128 singles matches in the main draw for each slam, plus qualifying. Add 250/500/1000
series tour events and there are prediction opportunities almost every week of the year.

---

## Goal

A 5-agent LangGraph system that predicts match outcomes with set-score breakdowns. The system
adds a dimension the NRL predictor lacks: an **Upset Detector** agent whose job is to
identify structural reasons why the lower-ranked player might win — because in tennis,
upsets are common and high-value to predict correctly.

---

## Stack

- **Language**: Python 3.12
- **Agent framework**: LangGraph 0.2+ (mix of sequential and parallel nodes)
- **LLM SDK**: langchain-anthropic
- **Infra**: AWS Lambda, EventBridge cron, DynamoDB, S3
- **IaC**: AWS CDK Python
- **Tests**: pytest + moto

---

## Data sources

### Primary sources

| Source | Data | Access method |
|---|---|---|
| ATP / WTA official API | Rankings, draw, match schedule, live results | Public REST API |
| Tennis Abstract (Jeff Sackmann) | Granular match stats, serve/return data, H2H going back to 1991 | CSV dataset + web scrape |
| tennisexplorer.com | H2H, surface records, tournament history | HTML scrape |
| ultimatetennisstatistics.com | Advanced stats — ACES, double faults, break points, fatigue metrics | HTML scrape |
| flashscore.com | Live scores, real-time results | HTML scrape or API |
| odds portals (Oddschecker/Bet365) | Pre-match odds | HTML scrape |

### Tennis Abstract dataset note

Jeff Sackmann's GitHub (github.com/JeffSackmann) contains:
- atp_matches_{year}.csv — every ATP match since 1968 with stats
- wta_matches_{year}.csv — WTA equivalent
- atp_rankings_{date}.csv — weekly ranking snapshots
These are downloadable CSVs, can be loaded into DynamoDB or S3, and updated weekly.
This is the backbone of the form and stats analysis — no API dependency for historical data.

### Spike required

Before building: write a throwaway script that:
1. Parses a Tennis Abstract CSV for a recent tournament
2. Pulls current draw from ATP API for an active event
3. Scrapes ultimatetennisstatistics.com for a specific player's serve stats
4. Checks flashscore.com for results latency after a match ends
5. Confirms H2H data is available for top-100 vs top-100 matchups

---

## Agent architecture

```
  match_id (player_a vs player_b, tournament, round)
     |
     v
 [Match Context Loader]      pull draw, rankings, tournament info, surface
     |
     +----------+----------+----------+
     |          |          |          |
     v          v          v          v
  [Stats     [Form &    [Matchup   [Upset
  Analyst]   Momentum]  Specialist] Detector]
     |          |          |          |
     +----------+----------+----------+
                           |
                           v
                      [Synthesis Judge]
                           |
                           v
                       [Output]        write to DynamoDB match_predictions table
```

Four specialist agents run in parallel, then feed a synthesis judge.

---

## LangGraph state

```python
class TennisMatchState(TypedDict):
    match_id: str
    tournament: TournamentContext    # name, surface, round, prize money
    player_a: PlayerProfile          # name, ranking, nationality, age
    player_b: PlayerProfile
    stats_analysis: StatsAnalysis    # from Stats Analyst
    momentum_analysis: MomentumAnalysis  # from Form & Momentum
    matchup_analysis: MatchupAnalysis    # from Matchup Specialist
    upset_analysis: UpsetAnalysis        # from Upset Detector
    final_prediction: TennisPrediction   # from Synthesis Judge
    agent_trace: list[TraceEntry]
```

---

## Node 1: Match Context Loader (no LLM)

Pure Python data assembly.

**Outputs**:
- tournament name, surface (Hard / Clay / Grass / Indoor Hard), round (R128/R64/.../Final)
- both players: ATP/WTA ranking, age, nationality, seeding (if applicable)
- tournament history: has either player won or gone deep in this tournament before?
- current draw: who each player could face in subsequent rounds (useful for motivation)
- is either player coming back from injury (withdraw/retirement in last tournament)?

---

## Node 2: Stats Analyst

**Model**: claude-haiku-4-5-20251001

**Task**: Assess each player's underlying serve and return performance on this surface.
Stats are the most objective signal — less susceptible to narrative bias.

**Tools**:

```python
@tool
def get_serve_stats(player_id: str, surface: str, num_matches: int = 20) -> ServeStats:
    """Ace rate, double fault %, 1st serve %, 1st serve win %, 2nd serve win %."""

@tool
def get_return_stats(player_id: str, surface: str, num_matches: int = 20) -> ReturnStats:
    """1st serve return win %, 2nd serve return win %, break point conversion %."""

@tool
def get_tiebreak_record(player_id: str, surface: str) -> TiebreakRecord:
    """Win % in tiebreaks — indicates clutch performance."""

@tool
def get_surface_win_rate(player_id: str) -> SurfaceRecord:
    """Career win % on Hard, Clay, Grass, Indoor Hard."""
```

**Analysis dimensions**:
1. **Service dominance**: High ace rate + high 1st serve win % = harder to break
2. **Return pressure**: High break point conversion % = opponent service games are
   under constant pressure
3. **Surface affinity**: Is one player significantly better on this surface?
4. **Serve/return balance**: Is this a serve-dominated match (likely tiebreaks)?
   Or will breaks be frequent (longer sets, more back-and-forth)?
5. **Tiebreak record**: In evenly-matched stats, tiebreak win % is a differentiator

**Output**:

```python
class StatsAnalysis(BaseModel):
    player_a_serve_rating: float    # 0-100 composite
    player_b_serve_rating: float
    player_a_return_rating: float
    player_b_return_rating: float
    surface_advantage: str | None   # player name who has surface edge, or None
    match_style_prediction: str     # "serve-dominated tiebreaks" / "break-heavy" / "balanced"
    stats_notes: str                # 200-300 words
    statistical_edge: str           # player name with overall stats edge, or "even"
```

---

## Node 3: Form & Momentum Agent

**Model**: claude-haiku-4-5-20251001

**Task**: Assess recent form trajectory and momentum going into this match. A player in
form is worth more than their ranking suggests; a player in a slump is worth less.

**Tools**:

```python
@tool
def get_recent_results(player_id: str, num_tournaments: int = 5) -> list[TournamentResult]:
    """Last N tournaments: round reached, wins, losses, retirement/walkover."""

@tool
def get_winning_streak(player_id: str) -> StreakInfo:
    """Current win/loss streak and previous streak."""

@tool
def get_fatigue_index(player_id: str, current_date: str) -> FatigueIndex:
    """Matches played in last 14 days, travel days, time since last rest week."""

@tool
def get_ranking_trajectory(player_id: str) -> RankingTrajectory:
    """Ranking over last 12 months — rising, falling, or stable?"""

@tool
def web_search(query: str) -> str:
    """For injury news, withdrawal history, player interviews, coaching changes."""
```

**Analysis dimensions**:
1. **Recent tournament depth**: Has the player been going deep (QF/SF/F) or losing early?
2. **Winning streak**: Players on 5+ match streaks have measurable momentum advantage
3. **Fatigue**: Played 5 matches in 6 days? Coming off a long match the day before?
4. **Ranking trajectory**: A player ranked 35 but trending toward 20 plays differently
   from one ranked 35 but trending toward 60
5. **Recent injury**: Return from injury or managed condition?
6. **Mental state**: Post-loss of final, post-big-win — can affect performance

**Output**:

```python
class MomentumAnalysis(BaseModel):
    player_a_momentum: Literal["STRONG", "NEUTRAL", "POOR"]
    player_b_momentum: Literal["STRONG", "NEUTRAL", "POOR"]
    player_a_fatigue_risk: bool
    player_b_fatigue_risk: bool
    momentum_edge: str | None    # player name or None
    form_notes: str              # 200-300 words
```

---

## Node 4: Matchup Specialist

**Model**: claude-sonnet-4-6 (upgrade — H2H analysis is the most nuanced reasoning task)

**Task**: Deep dive into the specific head-to-head record and playing-style compatibility
between these two players. Some players have a psychological or stylistic edge over an
opponent regardless of rankings.

**Tools**:

```python
@tool
def get_head_to_head(player_a_id: str, player_b_id: str) -> H2HRecord:
    """Full H2H: overall, by surface, by round (earlier rounds vs later rounds)."""

@tool
def get_playing_style(player_id: str) -> PlayingStyle:
    """Baseline/net player, aggressive/defensive, rally length preferences."""

@tool
def get_surface_h2h(player_a_id: str, player_b_id: str, surface: str) -> SurfaceH2H:
    """H2H restricted to this surface type."""

@tool
def get_tournament_h2h(player_a_id: str, player_b_id: str, tournament: str) -> TournamentH2H:
    """H2H at this specific tournament."""

@tool
def get_big_point_record(player_id: str) -> BigPointRecord:
    """Break point saved %, break point converted %, tiebreak % — high-pressure stats."""
```

**Analysis dimensions**:
1. **H2H dominance**: Does one player own the other? (3-0 in H2H is significant)
2. **Style matchup**: A big server vs a great returner; a clay-court baseline grinder
   vs a net rusher; an aggressive striker vs a counter-puncher
3. **Surface-specific H2H**: Overall 3-1 but 1-1 on clay — the surface H2H matters more
4. **Tournament venue**: Some players have psychological attachment to specific venues
5. **Set-score patterns**: Does one player typically win in straight sets, or does the
   other always push them to 5 sets?
6. **Big-point performance**: In tight matches between these two, who converts pressure?

**Output**:

```python
class MatchupAnalysis(BaseModel):
    h2h_record: str               # e.g. "Player A leads 4-2"
    surface_h2h: str              # H2H on this specific surface
    h2h_edge: str | None          # player name with H2H edge, or "even"
    style_advantage: str | None   # player whose style suits this matchup better
    psycho_edge: str | None       # player with psychological edge at this tournament
    matchup_notes: str            # 250-400 words
    matchup_verdict: str          # player name who matchup favours, or "neutral"
```

---

## Node 5: Upset Detector

**Model**: claude-haiku-4-5-20251001

**Task**: Specifically look for reasons the lower-ranked / underdog player could win.
This is a dedicated devil's advocate node. It operates independently of the other three
analysts and is specifically tasked with identifying structural upset conditions.

This node exists because the Judge (without a dedicated upset node) tends to be biased
toward the higher-ranked player, and tennis is a sport where upsets occur ~35% of the time.

**No tools** — the upset detector works only from the state context already populated
by the other nodes. It reads their outputs and the raw match context.

**Upset signals to search for**:
1. Higher-ranked player coming off a deep run + consecutive days of play (fatigue)
2. Lower-ranked player is significantly younger — better on faster surfaces
3. Lower-ranked player has a positive H2H record (e.g. 2-1 up despite ranking difference)
4. Playing style: underdog is a serve-heavy player on a fast surface — rankings are
   compressed by serve performance
5. Higher-ranked player is returning from injury, has a lingering niggle
6. Tournament round: first week R128/R64/R32 has higher upset rates than later rounds
7. Lower-ranked player is coming off a career-best tournament (momentum spike)
8. Seeding means higher-ranked player has already played 4+ matches in 5 days

**Output**:

```python
class UpsetAnalysis(BaseModel):
    upset_risk: Literal["LOW", "MODERATE", "HIGH"]
    upset_candidate: str          # the underdog's name
    upset_factors: list[str]      # 1-4 specific reasons
    upset_probability_adjustment: float  # suggested adjustment to favourite's win prob
    upset_notes: str              # 100-200 words
```

---

## Node 6: Synthesis Judge

**Model**: claude-sonnet-4-6

**Task**: Read all four analysis streams. Produce final match prediction with set score.

**Weighting framework** (soft guide — judge can override):

| Stream | Default weight | Condition for increased weight |
|---|---|---|
| Stats Analyst | 30% | Serve-dominated surface (Wimbledon, fast hard) |
| Form & Momentum | 25% | One player on 5+ match streak or injury return |
| Matchup Specialist | 30% | H2H > 5 meetings, clear style advantage exists |
| Upset Detector | 15% | Upset risk is MODERATE or HIGH |

**Output**:

```python
class TennisPrediction(BaseModel):
    predicted_winner: str
    confidence: Literal["LOW", "MEDIUM", "HIGH"]
    predicted_score: str            # e.g. "6-4, 6-3" or "7-6, 4-6, 6-4"
    predicted_sets: int             # 2 or 3 (best of 3) / 3, 4, or 5 (best of 5)
    upset_flagged: bool             # True if Upset Detector was high and judge heeded it
    key_factors: list[str]          # 2-4 items for display
    reasoning: str                  # 200-400 words
    win_probability_a: float
    win_probability_b: float
```

---

## Scoring

| Outcome | Score |
|---|---|
| Correct winner | 1.0 |
| Wrong winner | 0.0 |
| Correct set score (exact) | bonus 0.5 |
| Correct number of sets | bonus 0.25 |

Brier score for win probabilities, same as NRL predictor.

Metrics tracked:
- pick_rate (winner correct %)
- set_score_accuracy (exact set score %)
- upset_detection_rate (% of actual upsets where upset_flagged was True)
- false_upset_rate (% of upset_flagged that were not actual upsets)
- confidence_calibration (Brier by confidence tier)

---

## Scheduling

```
Tournament day begins:
  07:00 local  Draw + schedule scraper — pull day's matches
  09:00 local  Initial predictions generated for all day's matches
  30min pre-match  Re-run if lineup changes or weather delays announced
  +60min post-match  Scoring Lambda fires
  23:00 local  Daily metrics aggregation
```

---

## DynamoDB tables

| Table | PK | SK | Contents |
|---|---|---|---|
| tennis_matches | matchId | scrapedAt | draw info, players, round, surface |
| tennis_predictions | matchId | generatedAt | full prediction + agent outputs |
| tennis_results | matchId | resultAt | official score, winner, duration |
| tennis_players | playerId | statDate | serve/return stats snapshot |
| tennis_metrics | period | metricName | accuracy, upset detection, calibration |

matchId format: `{tournament-slug}-{round}-{player_a_slug}-v-{player_b_slug}`
e.g. `french-open-2026-r4-djokovic-v-alcaraz`

---

## Front end

Same Next.js + Tailwind + Amplify pattern. Match card shows:

- Predicted winner with win probability %
- Predicted set score
- Confidence badge
- Key factors (2-4)
- Upset flag badge (when upset_flagged = True)
- Post-match: actual score + result badge (correct / incorrect)
- Stats comparison panel: serve rating, return rating, momentum indicator

---

## Estimated build time

| Phase | Effort |
|---|---|
| Tennis data spike (ATP API + Tennis Abstract CSVs) | 1-2 days |
| Data models + DynamoDB tables | 0.5 day |
| Match card scraper + results scraper | 1-2 days |
| Stats Analyst node + tools | 1.5 days |
| Form & Momentum node + tools | 1.5 days |
| Matchup Specialist node + tools | 1.5 days |
| Upset Detector node (no tools) | 0.5 day |
| Synthesis Judge node | 1 day |
| Graph wiring + Lambda handler | 0.5 day |
| Scoring + metrics | 1 day |
| CDK infra | 0.5 day |
| Tests (TDD throughout) | included above |
| Front end | 1 day |

Total: ~13-15 dev days.

---

## Key differentiator vs NRL and horse racing

The Upset Detector is the unique agent in this system. NRL and horse racing predictors
can absorb upset signals into their main analysis agents, but tennis has such a high and
identifiable upset rate that a dedicated adversarial node pays for itself. Tracking
`upset_detection_rate` and `false_upset_rate` as separate metrics lets you tune the
Upset Detector independently from the rest of the system.

The set-score prediction is also unique — it adds a richer prediction surface. Getting
the winner right and the set score roughly right (e.g. predicting a 3-setter when it went
3 sets) is a more granular calibration signal than match winner alone.
