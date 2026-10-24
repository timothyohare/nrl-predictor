# 2026 Season Wrap-Up

Written 2026-10-24, after the grand final (round 31). All schedules are paused
for the off-season (see "Off-season state" at the end).

Data sources: `metrics` table (`2026-season` + per-round rows), `predictions`,
`results`, `simulation_predictions`, `claude_usage`, and a fresh run of
`scripts/backtest_elo_model.py` over the full season. Tracking started at
round 11, so rounds 1–10 are not in any of these numbers.

## Headline numbers

| Measure | Value |
|---|---|
| Correct picks (scored, rounds 11–31) | **75 / 123 = 61.0%** |
| Mean margin error | 10.3 pts |
| Brier score | 0.244 (0.25 = coin flip) |
| Baseline: always pick the home team | 70 / 125 = 56.0% |
| Baseline: betting market | **not measurable** — `odds` table is empty |
| Regular season vs finals (served picks) | 72/108 = 66.7% vs 4/9 = 44.4% |
| Best rounds | 20 and 23 (7/8) |
| Worst rounds | 13 (2/7), 27 (3/8), 30 (0/2) |

Confidence buckets were in the right *order* but badly over-stated:

| Confidence | Hit rate | Probability scoring assumes |
|---|---|---|
| HIGH | 24/35 = 68.6% | 85% |
| MEDIUM | 35/58 = 60.3% | 65% |
| LOW | 16/30 = 53.3% | 55% |

That gap — plus scoring every pick at a fixed 0.85/0.65/0.55 instead of the
model's own probability — is most of why the Brier score sits close to a coin
flip despite a 61% pick rate.

## Which predictor did best (like-for-like)

Each predictor version covered different rounds, so raw pick rates aren't
comparable. The table compares each version's live picks with what the Elo
model (backtest, no look-ahead) would have picked **on exactly the same matches**:

| Version | Matches | Live pick rate | Elo on same matches |
|---|---|---|---|
| v1.1 (single-loop Claude) | 12 | 50.0% | 75.0% |
| v1.2 (single-loop Claude + tools) | 24 | 62.5% | 70.8% |
| **v2.0 (LangGraph multi-agent Claude)** | 61 | **73.8%** | 67.2% |
| stats-elo-v1 (live, rounds 26–31 incl. finals) | 20 | 50.0% | 50.0% |

Full-season Elo backtest (rounds 12–31): 81/125 = **64.8%**, MAE 11.8, Brier
0.2475. Caveat: it is in-sample (home advantage was tuned on this season) and
cold-starts every team at 1500 in round 12.

## What worked

- **v2's multi-agent pipeline was the strongest predictor of the season** —
  +6.6 pts over Elo on the same 61 matches (about 4 extra correct picks; small
  sample, so suggestive rather than proven).
- **The Elo/Monte Carlo cutover saved the site.** Once the Claude path went down
  (round 25), switching to `stats-elo-v1` gave 8/8 coverage from round 26 on with
  no external dependency, and no measurable loss of accuracy against Elo itself.
- **LLM cost was never the problem.** `claude_usage` logs about $8.84 USD for the
  agent from May to August. The outages were about credit balance and
  reliability, not spend.
- **Margin bands** (`margin_low`/`margin_high`) gave the frontend an honest range
  instead of a false-precision point estimate.
- **The quality harness** (ci/verify/fuzz/mutation gates + BDD acceptance) caught
  regressions before deploy for the whole second half of the season.

## What didn't work

- **Reliability.** 350 of 1,092 prediction rows (32%) are `FAILED`. Round 25 had
  0/8 predictions for its entire duration, and the missing-predictions alarm
  didn't fire (since fixed, but never exercised by a real failure).
- **The betting-market comparison — the project's headline metric — never
  produced a number.** The `odds` table has zero rows: the key went invalid on
  2026-08-18 and was never rotated, and nothing alerted on an empty table.
- **The prompt tournament produced nothing usable.** `variant_metrics` has zero
  rows; `simulation_predictions` has 32 rows, all from `stats-elo-v1`. The
  Claude variants ran into credit exhaustion and were then paused.
- **The single-loop v1 agent lost to plain Elo** on the matches it covered, and
  intermittently emitted prose instead of JSON.
- **Finals.** 4/9 for both the live model and Elo. Elo has no notion of finals
  intensity, rest days, or the cross-over format.
- **Calibration.** HIGH confidence hit 68.6%, not 85%. The Elo backtest's own
  buckets were inverted (HIGH 64% < MEDIUM 70%), so its confidence labels carry
  no signal yet.
- **Year-specific hardcoding.** `"season": 2026` is baked into every EventBridge
  payload, and the grand final was scored as `round-31-game-1`. That slug is a
  finals matchId edge case worth checking before 2027.

## Ideas for next season

1. **Elo prior + LLM adjuster (an ensemble, not a replacement).** Feed the Elo
   win probability and margin to the LLM as a starting point, and let it adjust
   within a bounded range only when team news justifies it (spine changes,
   late outs, weather). This keeps v2's edge without making the site depend on
   the LLM: if the LLM call fails, the Elo number stands. Run it as a three-way
   tournament — Elo-only vs Elo + Qwen/DeepSeek (via a US host such as Fireworks
   or Together) vs Elo + Claude — and let `variant_metrics` choose. Check exactly
   what API usage the Max plan includes before relying on it for automated jobs.
2. **Fix calibration and scoring before tuning anything else.** Score Brier with
   the model's actual probability instead of fixed bucket values. Fit Elo's
   K-factor and home advantage on multi-season history. Warm-start 2027 from the
   2026 final ratings, regressed toward the mean, instead of everyone at 1500.
   Track a calibration curve on the accuracy page.
3. **A pre-season readiness check plus "silent zero" alarms.** One command (and a
   weekly scheduled check in season) that verifies the Anthropic/LLM credit
   balance, the odds key, the Tavily key, and that `odds`, `simulation_predictions`
   and `variant_metrics` gained rows this round. Every 2026 incident was a
   dependency failing quietly. Get the market baseline working on day one,
   because without it "beats the market" can't be measured.
4. **Go multi-sport, starting with the NFL now.** The Elo/Monte Carlo core,
   scoring, API and frontend are sport-agnostic; the draw/results/team-sheet
   scrapers, matchId, and team registry are not. Extract a per-sport adapter
   and prove it on the NFL. Its season is live right now (through February), so
   it's a real-data test of the abstraction during the NRL off-season, and
   nflverse publishes free schedules and results. Then AFL for the 2027 winter,
   using the Squiggle API (free fixtures/results, plus a public leaderboard of
   other models to benchmark against), and Rugby Union after that.
5. **Remove the season from config, and model finals separately.** Derive the
   season from the draw instead of hardcoding 2026, track from round 1, and add
   finals-specific inputs (rest days, finals experience) or at least shrink
   confidence in finals.

## Off-season state (2026-10-24)

- All 16 v1 EventBridge rules are disabled through `SEASON_ACTIVE = False` in
  `infra/v1_stack.py` (deployed; `aws events list-rules` shows every `nrl-*`
  rule `DISABLED`). The 3 v2 rules were already disabled.
- The local crontab's `v2/scripts/daily_update.sh` job is commented out. It had
  still been firing the v2 orchestrator every day.
- The site and API stay up so the 2026 results remain browsable. Idle cost is
  close to zero (see "AWS spend" below).
- The unused `nrl-predictor/supercoach-token` secret has been removed from the
  stack and deleted. It only ever held the placeholder `PENDING` and had never
  been accessed.
- **To re-enable for 2027:** set `SEASON_ACTIVE = True`, update the `"season"`
  payloads, `cdk deploy NrlPredictorStack`, uncomment the cron line, and run the
  readiness check from idea 3.

## AWS spend

From Cost Explorer, May–October 2026, in USD. **NRL Predictor's idle cost is
about $2–3 a month.** The rest of the account bill comes from other projects
and old backups, which are out of scope here.

| Item | Monthly | Notes |
|---|---|---|
| Secrets Manager | ~$1.20 | 3 secrets × $0.40 (was 4 before `supercoach-token` was removed) |
| Amplify builds | ~$1.00 | Shared with other Amplify apps; NRL's builds are mostly triggered by Dependabot merges to `main` |
| CloudWatch | $0–0.26 | 19 log groups, ~5 MB, none with a retention policy |
| DynamoDB | ~$0.02 | ~12 MB in on-demand tables, inside the free tier |
| Lambda, API Gateway, EventBridge, SNS | ~$0 | Nothing runs while the schedules are off |
| S3 (raw scrapes + CDK assets) | ~$0.09 | 0.1 GB + 3.6 GB |

**Recommendation: leave the stack deployed.** Tearing it down would save under
$3 a month and cost a full redeploy and re-seed before round 1.

Optional further savings:
- Move the remaining 3 secrets to SSM Parameter Store SecureString (free
  standard tier): saves ~$1.20 a month. This is a code change in the handlers
  and stacks, best done while preparing for 2027.
- Batch Dependabot updates monthly (or pause Amplify auto-builds on `main`) to
  cut off-season build minutes.
- Set log retention (e.g. 30 days) on the Lambda log groups. This is hygiene
  more than savings.
