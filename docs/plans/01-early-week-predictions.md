# Plan: Early-Week Predictions (Phase 7)

## Goal

Generate predictions on Tuesday afternoon after NRL team lists are announced (~4pm AEST), then update them on Thursday and Friday with fresher data (late changes, injury updates, weather). This lets the user submit tips to tipping competitions before Wednesday/Thursday deadlines.

## Background

- NRL team lists are announced Tuesday ~4pm AEST
- Current earliest prediction run is Thursday 5pm AEST
- The orchestrator already handles re-runs cleanly — each run creates a new prediction row with a fresh `generatedAt`. The API and frontend pick the most recent OK prediction per match.
- Team sheets may be incomplete on Tuesday (some coaches delay naming reserves). The agent handles this — it flags missing data and produces a lower-confidence prediction.

## Implementation Steps

### 1. Add Tuesday EventBridge schedule

**File:** `infra/stack.py`

Add a new rule:

```
Tuesday 06:30 UTC (16:30 AEST) — draw scraper + orchestrator
```

Targets: `draw_fn` + `orchestrator_fn` (same as Thursday). The draw scraper ensures we have the round's matches before the orchestrator fans out.

Also add `articles_fn` and `weather_fn` so the agent has context.

### 2. Add Wednesday morning refresh (optional)

Consider a Wednesday 08:00 AEST run of `articles_fn` only, to pick up any Tuesday-night injury news that might affect a Wednesday tip submission.

### 3. Track prediction generation number

**File:** `agent/lambda_handler.py`

Add a `generation` field to the prediction record:
- Count existing OK predictions for the same `matchId` and set `generation = count + 1`
- Tuesday predictions get `generation: 1`, Thursday gets `generation: 2`, etc.

This enables analysis of whether later predictions are more accurate than earlier ones.

### 4. Frontend: show prediction freshness

**File:** `frontend/components/MatchCard.tsx`

Display the `generatedAt` timestamp in a human-friendly way (e.g. "Predicted Tue 4:30pm" vs "Updated Thu 5pm"). Optionally show if the pick changed between generations.

### 5. Update CLAUDE.md

Add Tuesday schedule to the EventBridge schedule table.

## Testing

- [TEST] Verify orchestrator runs correctly when team sheets are partially available (some matches have sheets, some don't)
- [TEST] Verify API returns the most recent prediction when multiple exist for the same matchId
- Manual: trigger orchestrator for current round on a Tuesday, verify predictions appear

## Risks

- **Incomplete team sheets:** Some coaches don't name their 18th/reserve until Thursday. The agent will produce a prediction anyway with available data and flag uncertainty. The Thursday/Friday run replaces it with a more confident prediction.
- **Cost:** 8 extra Haiku calls/week = ~$0.10. Negligible.

## Definition of Done

- [ ] Tuesday 16:30 AEST EventBridge rule triggers draw + orchestrator
- [ ] Predictions appear in the API within 10 minutes of Tuesday run
- [ ] Thursday/Friday runs overwrite Tuesday predictions (most recent shown)
- [ ] `generation` field tracks which run produced each prediction
- [ ] CLAUDE.md updated with new schedule
