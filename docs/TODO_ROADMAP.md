# NRL Predictor — Roadmap

Execution order reflects dependencies, effort, and value. Each item has a detailed plan in `docs/plans/`.

---

## Tier 1 — Quick Wins (small effort, immediate value)

### Phase 7A: Early-Week Predictions

**Status:** Not started
**Plan:** [plans/01-early-week-predictions.md](plans/01-early-week-predictions.md)
**Summary:** Run predictions Tuesday after team lists drop, update Thursday/Friday. Enables tipping comp use.
**Effort:** Small — one EventBridge rule + minor frontend change
**Cost:** ~$0.10/week

### Phase 7B: Momentum Decay Weighting

**Status:** Not started
**Plan:** [plans/06-momentum-decay-weighting.md](plans/06-momentum-decay-weighting.md)
**Summary:** Replace flat "last 6 games" with exponential decay weighting. Captures momentum direction — a team on a 3-game win streak after 3 losses looks very different from the reverse.
**Effort:** Small — pure computation on existing data, no new tables or APIs
**Cost:** Zero

---

## Tier 2 — Prediction Quality (moderate effort, direct accuracy improvement)

### Phase 7C: Venue-Specific Models

**Status:** Not started
**Plan:** [plans/05-venue-specific-models.md](plans/05-venue-specific-models.md)
**Summary:** Venue profiles with historical home win rate, avg scores, weather impact notes, surface/roof info. Replace generic "check weather" with venue-aware analysis.
**Effort:** Medium — new table, seed script, new tool
**Cost:** Zero (computes from existing data)

### Phase 7D: Coaching Matchup Analysis

**Status:** Not started
**Plan:** [plans/07-coaching-matchup-analysis.md](plans/07-coaching-matchup-analysis.md)
**Summary:** Coach-vs-coach records filtered to current tenures. A team's H2H under a different coach is misleading. Static coach map + compute from existing results.
**Effort:** Medium — new tool, static data map
**Cost:** Zero

### Phase 7E: Trap Game Detection

**Status:** Not started
**Plan:** [plans/08-trap-game-detection.md](plans/08-trap-game-detection.md)
**Summary:** Schedule context analysis: sandwich games, emotional letdowns, dead rubbers, short turnarounds, revenge games. Composite trap score (0-5) flags upset-prone matches.
**Effort:** Medium — new tool computing from existing draw/results data
**Cost:** Zero

### Phase 7F: Player Combination Synergy

**Status:** Not started
**Plan:** [plans/09-player-combination-synergy.md](plans/09-player-combination-synergy.md)
**Summary:** Track how many games each team's spine (1-6-7-9) have played together. Flag new combinations with <5 games as a hidden vulnerability. Combination experience > individual quality.
**Effort:** Medium — new tool, historical team sheet analysis
**Cost:** Zero

---

## Tier 3 — External Data (new data sources, moderate-high effort)

### Phase 8: Betting Market Comparison

**Status:** Not started
**Plan:** [plans/02-betting-market-comparison.md](plans/02-betting-market-comparison.md)
**Summary:** Scrape odds independently (NOT as agent input). Track market accuracy alongside prediction accuracy. Flag outliers where our pick disagrees with the market.
**Effort:** High — new scraper, new table, new API endpoint, frontend component
**Cost:** Free tier API (the-odds-api.com)

---

## Tier 4 — Meta-Optimisation (high effort, compounding value)

### Phase 9: Prompt Tournament

**Status:** Not started
**Plan:** [plans/03-prompt-tournament.md](plans/03-prompt-tournament.md)
**Summary:** Run 20-50 prompt variants per match. Score all variants after results. Promote the best-performing prompt after statistical significance (~6 rounds). Hyperparameter sweep over prompt space.
**Effort:** High — new tables, tournament runner, scoring pipeline, dashboard
**Cost:** ~$4/round ($108/season) on Haiku

### Phase 10: Self-Modifying Prompt (Deferred)

**Status:** Deferred — superseded by Phase 9
**Plan:** [plans/04-self-modifying-prompt.md](plans/04-self-modifying-prompt.md)
**Summary:** Post-round prompt editor agent rewrites the system prompt from lessons. Deferred because 1-week feedback cycle is too slow for reliable signal. Implement only if Phase 9 proves impractical.
**Effort:** Medium
**Cost:** ~$0.05/week

---

## Execution Order

| Priority | Phase | Why this order |
|----------|-------|----------------|
| 1 | 7A Early-Week Predictions | Unblocks tipping comp immediately |
| 2 | 7B Momentum Decay | Zero cost, zero risk, immediate accuracy signal |
| 3 | 7C Venue Profiles | Enriches every prediction with ground-specific context |
| 4 | 7D Coaching Matchups | Captures tactical dimension missing from team H2H |
| 5 | 7E Trap Game Detection | Targets the hardest predictions (upsets) |
| 6 | 7F Spine Synergy | Requires good team sheet history; benefits from earlier phases |
| 7 | 8 Betting Markets | Independent workstream, can run in parallel with 7C-7F |
| 8 | 9 Prompt Tournament | Needs all prediction improvements in place first to test them |
| 9 | 10 Self-Modifying Prompt | Only if Phase 9 is impractical |

Phases 7B-7F can be done in any order — they're independent prediction quality improvements. The order above is by estimated impact-to-effort ratio.
