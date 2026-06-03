# Plan: Self-Modifying Prompt (Phase 10 — Deferred)

## Status: Deferred

This plan is superseded by Phase 9 (Prompt Tournament) which achieves the same goal more reliably. The tournament explores the prompt space empirically with statistical rigour, while this approach relies on a single agent's judgement about what to change — and has a 1-week feedback cycle that's too slow to distinguish signal from noise.

**Implement this only if:** the tournament (Phase 9) proves too expensive or complex, and you want a simpler "good enough" alternative.

## Goal

After each round's retrospectives complete, a "prompt editor" agent reads the accumulated lessons and rewrites the prediction system prompt. The new prompt is versioned and used for the next round. Over time, the prompt evolves based on empirical feedback.

## How It Would Work

```
Retrospectives complete (Sunday)
  → Prompt Editor Lambda triggers
     ├─ reads all lessons from current season (retrospectives table)
     ├─ reads current system prompt + version history
     ├─ calls Claude Sonnet: "Given these lessons, suggest improvements to the prompt"
     ├─ validates new prompt (schema check, length bounds)
     ├─ writes new prompt to prompts table with incremented version
     └─ next orchestrator run picks up the new prompt
```

## New AWS Resources

### DynamoDB table: `prompts`

| Field | Type | Description |
|-------|------|-------------|
| `promptId` (PK) | String | Always "production" (or "staging" for testing) |
| `version` (SK) | String | Semantic version, e.g. "v1.3" |
| `prompt_text` | String | Full system prompt |
| `changes` | String | What was changed from previous version |
| `lessons_used` | List | Which lessons informed this change |
| `createdAt` | String | ISO timestamp |

## Implementation Steps

### 1. Create `prompt_editor/editor.py`

- `edit_prompt(current_prompt, lessons, client)` — calls Claude Sonnet with:
  - The current system prompt
  - All season lessons
  - Instructions: "Suggest ONE specific, measurable change. Explain your reasoning. Output the complete new prompt."
- Validates: new prompt still contains required schema, version tag, all 7 assessment steps
- Returns new prompt text + change description

### 2. Create `prompt_editor/lambda_handler.py`

- Triggered after retrospectives complete (EventBridge or async from scoring)
- Reads current prompt from `prompts` table
- Reads lessons from `retrospectives` table
- Calls editor
- Writes new version to `prompts` table
- Does NOT auto-deploy — requires manual review and promotion

### 3. Update `agent/prompt.py`

- `build_system_prompt()` checks `prompts` table for active version
- Falls back to hardcoded prompt if table read fails
- Logs which prompt version was used

### 4. CDK updates

- New `prompts` DynamoDB table
- New `prompt-editor` Lambda
- EventBridge trigger or async invocation from scoring

## Why This Is Risky

1. **1-week cycle:** Each prompt change is tested on only 8 matches before the next edit. Statistical noise dominates. A change that looks good after 1 round might be random.

2. **Compounding errors:** If the editor makes a bad change, the next round's lessons are based on a degraded prompt, which could lead to further bad edits. There's no mechanism to detect and revert degradation quickly.

3. **Single agent's judgement:** The editor is one Claude call deciding what to change. It might fixate on recent losses and overfit, or make changes that sound logical but don't improve accuracy.

4. **Prompt drift:** Over many rounds, the prompt could drift far from the original intent without any single change being obviously wrong.

## Mitigations (if implementing)

- **A/B test:** Run both old and new prompt for 1 round before committing
- **Revert threshold:** If pick rate drops >10% over 2 consecutive rounds, auto-revert to last known good version
- **Change size limit:** Editor must change only ONE aspect per round
- **Human review gate:** New prompts go to "staging" and require manual promotion

## Cost

- 1 Sonnet call/week (~$0.05)
- Negligible DynamoDB

## Definition of Done

- [ ] Prompt editor generates valid new prompts from lessons
- [ ] New prompts stored in `prompts` table with version history
- [ ] Agent reads active prompt from table (with hardcoded fallback)
- [ ] Manual promotion gate — no auto-deploy
- [ ] Revert mechanism if accuracy drops
