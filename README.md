# NRL Predictor

Predictions for every NRL match, published on a Next.js frontend. Scrapes official team sheets and results, then predicts each match with a local Elo + Monte Carlo model (`stats-elo-v1`) — no external LLM call on the live path.

Live at **https://nrl-predictor.ohare.id.au/**.

## Architecture

```
EventBridge cron
  → Orchestrator Lambda
      ├─ scrapes draw                              (writes teams)
      ├─ scrapes team sheets inline (per match)    (writes teams)
      └─ predicts every match locally               (Elo + Monte Carlo, stats-elo-v1)
            → predictions DynamoDB
               → API Gateway (joins predictions + results + retrospectives)
                  → Next.js frontend (Amplify)
```

**2026-08-23:** cut over from an Anthropic Claude ReAct-loop agent to the local
stats-elo-v1 model after an Anthropic account credit exhaustion incident left
main predictions down for several days. See `docs/plans/10-elo-monte-carlo-predictor.md`
(Phase 3) for the full history. The Claude agent Lambda still exists and is
callable ad-hoc per match for manual backfill — it's just no longer on the
automatic per-round path.

Standalone scrapers (`ladder`, `articles`, `weather`, `results`, `odds`) are wired to their own EventBridge schedules.

A prompt tournament runs 8 prompt variants in parallel per match. The tournament scorer runs Sunday evening to compare variant accuracy and find the best prompt configuration.

Post-match: `scripts/score_round.py` invokes the scoring Lambda per matchId; scoring writes to `results`, aggregates into `metrics`, and async-triggers the retrospective Lambda.

---

## Quick reference

| Want to … | Do this |
|---|---|
| Check which commit is deployed | `git log --oneline -1` (build SHA shown in the site footer) |
| Trigger a round of predictions now | See [Invoking the orchestrator](#invoking-the-orchestrator-manually-for-backfill--catch-up) below |
| Verify the API | `curl https://2jjj64x7ih.execute-api.ap-southeast-2.amazonaws.com/predictions/12` |
| Score a completed round | See [Scoring a completed round](#scoring-a-completed-round) below |

---

## Setup from scratch

### Prerequisites

- Python 3.12+
- Node.js 22 LTS
- AWS CLI configured for account `810429055117`, region `ap-southeast-2`
- CDK CLI: `npm install -g aws-cdk`

### 1. Python environment

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. Bootstrap CDK (first time only)

```bash
cd infra
cdk bootstrap aws://810429055117/ap-southeast-2
```

### 3. Populate API keys in Secrets Manager

```bash
aws secretsmanager put-secret-value \
  --secret-id nrl-predictor/anthropic-api-key \
  --secret-string "sk-ant-..." \
  --region ap-southeast-2

aws secretsmanager put-secret-value \
  --secret-id nrl-predictor/tavily-api-key \
  --secret-string "tvly-..." \
  --region ap-southeast-2

aws secretsmanager put-secret-value \
  --secret-id nrl-predictor/odds-api-key \
  --secret-string "..." \
  --region ap-southeast-2
```

Get the Anthropic key from [console.anthropic.com](https://console.anthropic.com), the Tavily key from [app.tavily.com](https://app.tavily.com), and the odds API key from [the-odds-api.com](https://the-odds-api.com).

### 4. Deploy the CDK stack

```bash
cd infra
source ../.venv/bin/activate
cdk deploy --require-approval never
```

Note the `ApiEndpoint` value from the stack outputs — you'll need it for Amplify.

### 5. Seed historical data (backfill)

After the stack is deployed and the `results` table is live, seed two seasons of historical match results:

```bash
RESULTS_TABLE=results RAW_BUCKET=nrl-predictor-raw-scrapes AWS_DEFAULT_REGION=ap-southeast-2 \
  .venv/bin/python3 -m scrapers.nrl.backfill --seasons 2025 2026
```

Expected: ~430 records (27 rounds × 8 matches × 2 seasons).

### 6. Seed prompt tournament variants

```bash
AWS_DEFAULT_REGION=ap-southeast-2 python3 -m tournament.seed_variants
```

Seeds 8 prompt variants (baseline + 7 experimental) into the `prompt_variants` table for the prompt tournament.

### 7. Front end

```bash
cd frontend
npm install
npm run build   # verify no type errors before connecting Amplify
```

#### Amplify hosting

> **Read this whole section before clicking anything.** Amplify Gen 1 decides framework and platform at app *creation time*. If it auto-detects the app as a static "Web" site (instead of Next.js SSR), patching the platform later via CLI does **not** fix it — the `framework` and `customRules` fields stay wrong and Amplify's Next.js adapter never runs. The fix is to delete and recreate, so it's worth getting this right the first time. The repo intentionally has **no `amplify.yml`** so Amplify auto-detects Next.js from `frontend/package.json`.

**Step-by-step (Amplify console):**

1. **New app → Host web app → GitHub**, authorise the AWS Amplify GitHub App, and select repo + branch `main`.

2. **Critical: configure as monorepo.** On the build settings page:
   - Toggle **"My app is a monorepo"** ON
   - Set **App root** to `frontend`
   - Amplify will rescan and the **Framework** field at the top of the page should change to **"Next.js - SSR"** — *verify this before continuing*. If it still shows "Web", do not deploy — something is wrong with the detection and deploying anyway will lock you into a broken static app.

3. **Add environment variables on the same page** (do not skip and add them later — if the first build runs without them, you'll be debugging mysterious 500s):
   - `API_GATEWAY_URL` = the `ApiEndpoint` output from the CDK stack
   - `NEXT_PUBLIC_API_BASE_URL` = same value

4. Click **Save and deploy**. First build takes ~3 minutes.

**Verify SSR is actually working** (don't skip this — a "successful" build can still deploy as a broken static shell):

```bash
APP_ID=<your-app-id>
curl -si https://main.$APP_ID.amplifyapp.com/ | head -5
```

You want `HTTP/2 200`, `x-powered-by: Next.js`, and `server: CloudFront` (or no server header). If you see `server: AmazonS3` → Amplify deployed as static. Delete the app and start over with step 2 fixed.

```bash
aws amplify get-branch --app-id $APP_ID --branch-name main \
  --region ap-southeast-2 --query "branch.framework"
```

Expect `"Next.js - SSR"`. If it says `"Web"`, same thing — delete and recreate.

**Common mistakes that lock you into a broken app:**
- Skipping the monorepo toggle on the build settings page (Amplify scans repo root, sees `pyproject.toml` instead of `package.json`, falls back to detecting it as a static site)
- Forgetting env vars and adding them later (env var changes alone don't fix framework/platform misdetection)
- Trying to fix a misdetected app via `aws amplify update-app --platform WEB_COMPUTE` — this only updates one of several fields that need to be consistent

#### Custom domain

- In Amplify console: **Domain management → Add domain → `ohare.id.au`**, set subdomain to `nrl-predictor`
- Amplify auto-updates Route 53 when the hosted zone is in the same AWS account — no manual DNS edit needed
- SSL cert validation takes 5–30 min; the domain won't resolve until the cert is issued

### 8. Anthropic spend limit

In [console.anthropic.com](https://console.anthropic.com) → Settings → **Limits**:
- Monthly hard cap: **$40 USD**
- Email alert at: **$20 USD**

---

## Running tests

```bash
# All tests (moto mocks all AWS — no real credentials needed)
pytest

# Single file
pytest tests/scrapers/test_scraper_draw.py -v

# Single test
pytest tests/agent/test_tool_get_team_sheet.py::test_returns_correct_team_sheet -v
```

If boto3 complains about missing credentials, set dummy values:

```bash
export AWS_ACCESS_KEY_ID=test
export AWS_SECRET_ACCESS_KEY=test
export AWS_DEFAULT_REGION=ap-southeast-2
```

---

## Deployed resources

| Resource | Value |
|----------|-------|
| API Gateway | `https://2jjj64x7ih.execute-api.ap-southeast-2.amazonaws.com` |
| Agent Lambda | `nrl-predictor-agent` |
| Raw S3 bucket | `nrl-predictor-raw-scrapes` |
| AWS region | `ap-southeast-2` |
| AWS account | `810429055117` |

### DynamoDB tables

| Table | Purpose |
|-------|---------|
| `predictions` | Agent output, one item per match per generation |
| `teams` | Draw rows keyed by `{matchId}#{home\|away}` + team-sheet rows keyed by NRL numeric matchId |
| `results` | Scored match results (two rows per match — raw scrape + scored) |
| `metrics` | Aggregated round/season accuracy + per-prompt-version + per-confidence pick rates |
| `retrospectives` | Post-match Claude analysis comparing prediction vs outcome |
| `match_stats` | Tavily search snippets used as input to the retrospective |
| `nrl-rate-limits` | API rate limiting (ephemeral, TTL-based) |
| `claude_usage` | Monthly token spend tracking |
| `injuries` | Extracted injury mentions from articles |
| `weather` | Cached weather forecasts |
| `odds` | Betting market odds from the-odds-api.com (comparison only, never agent input) |
| `prompt_variants` | Tournament prompt variants (8 seeded) |
| `simulation_predictions` | Tournament variant predictions per match |
| `variant_metrics` | Tournament variant accuracy metrics |

---

## EventBridge schedule

All times converted to AEST for readability. AEDT = UTC+11 (summer), AEST = UTC+10 (winter).

| Rule | AEST | Targets |
|------|------|---------|
| Tuesday | 16:30 | Draw + articles + weather + **orchestrator** (early predictions after team lists) |
| Wednesday | 18:00 | Draw scraper |
| Thursday | 17:00 | Ladder + articles + weather + **orchestrator** (update predictions before Thu 6pm games) |
| Friday | 17:00 | Articles + weather + **orchestrator** (update before Fri 6pm games) |
| Friday | 22:00 | Articles + weather + **orchestrator** (re-run for late Fri / weekend games) |
| Saturday | 09:00 | Articles + weather + **orchestrator** (refresh for Sat / Sun games) |
| Sunday | 20:00 | **Tournament scorer** (score variant predictions after weekend results) |

The orchestrator scrapes the draw, scrapes team sheets inline, and predicts every match synchronously via the local Elo + Monte Carlo model — no external API call, so no rate limit or stagger on this path (2026-08-23 cutover; see Architecture above).

The odds scraper and tournament orchestrator also run alongside the main orchestrator on Tuesday/Thursday/Friday schedules.

---

## Re-deploying after code changes

```bash
cd infra
source ../.venv/bin/activate
cdk deploy --require-approval never
```

Amplify rebuilds automatically on every push to `main`.

---

## Invoking the orchestrator manually (for backfill / catch-up)

The orchestrator is the normal path to generate a round's predictions. Use it when a scheduled run misses, or when you want predictions earlier than the cron fires.

```bash
AWS_DEFAULT_REGION=ap-southeast-2 aws lambda invoke \
  --function-name nrl-predictor-orchestrator \
  --payload '{"season": 2026, "round": 12}' \
  --cli-binary-format raw-in-base64-out \
  --cli-read-timeout 600 \
  /tmp/orch_out.json && cat /tmp/orch_out.json
```

Returns `{"round": N, "matches": K, "predicted": [...matchIds]}`. Predictions are written synchronously (local Elo + Monte Carlo model, no external API call) — the orchestrator invocation itself completes with every match already in the `predictions` table, typically a few minutes (draw + team-sheet scrapes inline dominate the runtime).

Use `"round": "current"` to let the NRL API decide which round is in progress.

### Invoking a single Lambda directly

```bash
# Just the draw scraper (writes to teams table)
aws lambda invoke \
  --function-name nrl-predictor-draw-scraper \
  --payload '{"season": 2026, "round": 12}' \
  --cli-binary-format raw-in-base64-out \
  --region ap-southeast-2 \
  /tmp/response.json

# Just the Claude agent for one match (manual/backfill only — not on the
# automatic path since the 2026-08-23 stats-elo-v1 cutover) — matchId is
# round-qualified, e.g. round-12-broncos-v-raiders
aws lambda invoke \
  --function-name nrl-predictor-agent \
  --payload '{"matchId": "round-12-broncos-v-raiders", "round": 12}' \
  --cli-binary-format raw-in-base64-out \
  --region ap-southeast-2 \
  /tmp/response.json
```

---

## Scoring a completed round

After a round finishes, scrape the results and then invoke the scoring Lambda for each match:

### 1. Scrape results

```bash
aws lambda invoke \
  --function-name nrl-predictor-results-scraper \
  --payload '{"season": 2026, "round": 12}' \
  --cli-binary-format raw-in-base64-out \
  --region ap-southeast-2 \
  /dev/null
```

### 2. Score predictions and trigger retrospectives

```bash
# Preview (no invocations)
AWS_DEFAULT_REGION=ap-southeast-2 python3 scripts/score_round.py --round 12 --season 2026 --dry-run

# Run for real
AWS_DEFAULT_REGION=ap-southeast-2 python3 scripts/score_round.py --round 12 --season 2026
```

The scoring Lambda writes scored results to `results`, aggregates accuracy into `metrics`, and async-triggers the retrospective Lambda for each match. Retrospectives appear in the API response (under `retrospective`) ~30–60 seconds after scoring completes.

---

## Smoke-testing the API

```bash
API=https://2jjj64x7ih.execute-api.ap-southeast-2.amazonaws.com

curl $API/health
curl $API/predictions/12
curl $API/accuracy
```

Each prediction in the response carries a `result` field once the match has been scored — `{ winner, homeTeam, awayTeam, homeScore, awayScore, margin }` — which the front end uses to render the actual score next to the prediction. An `odds` field is joined when market data is available, with an `is_outlier` flag when the prediction disagrees with the market.
