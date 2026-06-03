# Plan: Prompt Tournament / Multi-Prompt Simulation (Phase 9)

## Goal

Run 20-50 prompt variants per match each round against identical input data. Score every variant after results come in. After 3-4 rounds of statistical signal, promote the best-performing prompt to production. This is a hyperparameter sweep over the prompt space.

## Why Not Monte Carlo?

True Monte Carlo varies random inputs to estimate distributions. This is closer to a **prompt tournament** or **hyperparameter sweep** — we fix the inputs (same match data) and vary the prompt to find which framing produces the most accurate predictions. The randomness comes from LLM sampling temperature, which adds useful variance.

## Architecture

```
Tournament Runner Lambda
  ├─ reads prompt_variants table (20-50 variants)
  ├─ for each variant × each match:
  │     invoke agent with variant prompt
  │     write to simulation_predictions table
  └─ stagger calls to respect rate limits

After results:
  Tournament Scorer Lambda
  ├─ reads simulation_predictions + results
  ├─ scores every variant for the round
  ├─ writes to variant_metrics table
  └─ promotes best variant if significance threshold met
```

## New AWS Resources

### DynamoDB tables

**`prompt_variants`** (PK: `variantId`, SK: `version`)

| Field | Description |
|-------|-------------|
| `variantId` | e.g. "heavy-home-advantage", "form-over-h2h" |
| `version` | ISO timestamp of when variant was created |
| `prompt_template` | Full system prompt text |
| `hypothesis` | What this variant tests (e.g. "Weighting home advantage +2pts") |
| `active` | Boolean — include in tournament |
| `dimensions` | Which parameters this variant tweaks |

**`simulation_predictions`** (PK: `matchId#variantId`, SK: `generatedAt`)

| Field | Description |
|-------|-------------|
| `matchId` | Standard matchId |
| `variantId` | Which prompt variant produced this |
| `generatedAt` | ISO timestamp |
| `predicted_winner` | Team nickname |
| `predicted_margin` | Integer |
| `confidence` | LOW/MEDIUM/HIGH |
| `reasoning` | Truncated to 500 chars to save storage |

**`variant_metrics`** (PK: `variantId`, SK: `period`)

| Field | Description |
|-------|-------------|
| `variantId` | Prompt variant identifier |
| `period` | e.g. "round-12", "season-2026" |
| `correct_picks` | Count |
| `total_picks` | Count |
| `pick_rate` | correct_picks / total_picks |
| `avg_margin_error` | Mean |
| `brier_score` | Mean |
| `rounds_active` | How many rounds this variant has been tested |

## Prompt Dimensions to Vary

Each variant should tweak ONE dimension to isolate its effect:

1. **Home advantage weighting** — "Home advantage is worth approximately N points" (vary N: 0, 2, 4, 6)
2. **Form vs H2H priority** — "Weight recent form more heavily than historical H2H" vs opposite
3. **Confidence calibration** — "Only use HIGH confidence when 3+ factors align" vs "Use HIGH when any 2 factors strongly align"
4. **Injury impact scaling** — "A missing spine player (1, 6, 7, 9) reduces team strength by ~15%" vs 10% vs 20%
5. **Weather sensitivity** — "Rain increases the home team's advantage" vs "Rain compresses margins"
6. **Reasoning structure** — Bottom-up (data first, verdict last) vs top-down (hypothesis first, then validate)
7. **Margin conservatism** — "When uncertain, predict a closer margin" vs "Commit to your best estimate"
8. **Upset detection** — "Actively look for upset conditions: away team with superior form at a neutral/poor-travel venue"
9. **Temperature** — Run same prompt at temperature 0.3, 0.5, 0.7, 1.0

## Implementation Steps

### 1. [TEST] Write `tests/tournament/test_variant_runner.py`

- Test that runner iterates variants × matches
- Test that results are written to simulation_predictions
- Test rate limiting / stagger logic

### 2. [CODE] Create `tournament/variant_runner.py`

- `run_tournament(round_number, season)` — main entry point
- Reads active variants from `prompt_variants` table
- For each variant × match: calls the agent with the variant's prompt
- Writes prediction to `simulation_predictions`
- Respects rate limiting: 8s stagger between calls (configurable)

### 3. [CODE] Create `tournament/lambda_handler.py`

- EventBridge-triggered after the main orchestrator completes
- Invokes `run_tournament()` for the current round

### 4. [TEST] Write `tests/tournament/test_variant_scorer.py`

- Test scoring logic across variants
- Test statistical significance calculation
- Test promotion logic

### 5. [CODE] Create `tournament/variant_scorer.py`

- `score_tournament(round_number, season)` — scores all variants for a round
- `aggregate_variant_metrics(variant_id, season)` — season-to-date metrics
- `should_promote(variant_id, baseline_variant_id)` — statistical test (binomial test or chi-squared) to determine if variant is significantly better than production
- `promote_variant(variant_id)` — copies variant prompt to production `agent/prompt.py` and bumps PROMPT_VERSION

### 6. [CODE] Create `tournament/seed_variants.py`

- Script to generate initial 20-50 variants from the base prompt
- Each variant has a clear hypothesis and tweaks one dimension
- Stores in `prompt_variants` table

### 7. [CODE] CDK updates

- Three new DynamoDB tables
- Tournament runner Lambda (longer timeout: 15 min for 50 variants × 8 matches)
- Tournament scorer Lambda
- EventBridge: run tournament after orchestrator (Saturday morning), score after results scraper
- IAM grants

### 8. [CODE] API endpoint: `/tournament/leaderboard`

- Returns variant rankings with confidence intervals
- Shows which dimensions correlate with accuracy

### 9. [CODE] Frontend: tournament dashboard

- Leaderboard table: variant, pick rate, margin error, Brier, rounds active
- Highlight production prompt vs challengers
- Show which dimensions are winning

## Rate Limiting and Cost

**Per round (50 variants × 8 matches = 400 calls):**
- Haiku: 400 × ~10K input tokens × $0.0008/1K = ~$3.20 input + output ≈ **$4/round**
- Season (27 rounds): ~$108

**To stay under 50K tokens/minute:**
- 400 calls at 10K tokens each = 4M tokens total
- At 50K/min limit, minimum run time = 80 minutes
- Stagger: 12s between calls = 80 min total. Fits in a 15-min Lambda if parallelised across multiple Lambdas, otherwise needs Step Functions or a longer-running compute (ECS/Fargate).

**Practical approach:** Run the tournament on a smaller subset initially (20 variants) to validate the approach before scaling up.

## Statistical Significance

With 8 matches/round, a variant needs ~4 rounds (32 matches) to show a statistically significant difference of 10 percentage points in pick rate (p < 0.05, binomial test).

After 4 rounds: if variant A picks 75% correctly (24/32) vs baseline 62.5% (20/32), the binomial test p-value is ~0.14 — not yet significant. After 6 rounds (48 matches): 77% (37/48) vs 62.5% (30/48) → p ≈ 0.04 — significant.

**Implication:** Plan for a 6-round (6-week) tournament before promoting. This is a feature of the NRL season structure, not a limitation of the approach.

## Risks

- **Cost at scale:** 50 variants is ~$4/round. Monitor and reduce if needed.
- **Rate limits:** 400 Haiku calls need careful staggering. May need Step Functions or multiple staggered Lambda invocations.
- **Overfitting:** A variant might win by luck over 6 rounds. Mitigate by requiring significance AND consistent performance (no single-round spikes).
- **Prompt interaction effects:** Tweaking home advantage AND form weighting simultaneously makes it hard to isolate which change helped. Keep variants single-dimension.

## Definition of Done

- [ ] 20+ prompt variants seeded in `prompt_variants` table
- [ ] Tournament runner executes all variants for a round within rate limits
- [ ] All variant predictions scored after results come in
- [ ] Leaderboard API endpoint returns ranked variants
- [ ] Statistical significance test identifies winning variants after 4-6 rounds
- [ ] Manual promotion process: review winning variant, update production prompt
- [ ] Cost stays under $5/round
