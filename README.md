# NRL Predictor

AI-powered predictions for every NRL match. Scrapes official team sheets, runs Claude to produce a written prediction with confidence level and key factors, and publishes results on a Next.js frontend.

## Architecture

```
EventBridge cron
  → Scraper Lambdas (draw, team sheet, ladder, results, weather, articles)
  → DynamoDB + S3
  → Agent Lambda (Anthropic Claude, ReAct loop)
  → predictions DynamoDB
  → API Gateway
  → Next.js frontend (Amplify)
```

Post-match: another cron triggers the scoring Lambda, which writes to `results`, then the metrics Lambda aggregates into `metrics`.

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
```

Get the Anthropic key from [console.anthropic.com](https://console.anthropic.com) and the Tavily key from [app.tavily.com](https://app.tavily.com).

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

### 6. Front end

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

### 7. Anthropic spend limit

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
| `teams` | Team sheets keyed by `{matchId}#{home\|away}` |
| `results` | Scored match results |
| `metrics` | Aggregated round/season accuracy |
| `nrl-rate-limits` | API rate limiting (ephemeral, TTL-based) |
| `claude_usage` | Monthly token spend tracking |
| `injuries` | Extracted injury mentions from articles |
| `weather` | Cached weather forecasts |

---

## EventBridge schedule

| Rule | UTC time | Action |
|------|----------|--------|
| Wednesday | 08:00 | Draw scraper |
| Thursday | 12:00 | Draw + ladder |
| Friday | 04:00 | Team sheets + articles |
| Friday | 12:00 | Team sheets + weather + articles + agent |
| Friday | 23:00 | Team sheets + weather + articles + agent (re-run) |

All crons are in UTC. AEST = UTC+10, AEDT = UTC+11.

---

## Re-deploying after code changes

```bash
cd infra
source ../.venv/bin/activate
cdk deploy --require-approval never
```

Amplify rebuilds automatically on every push to `main`.

---

## Invoking a Lambda manually (for testing)

```bash
# Trigger the draw scraper
aws lambda invoke \
  --function-name nrl-predictor-draw-scraper \
  --payload '{"season": 2026}' \
  --region ap-southeast-2 \
  /tmp/response.json && cat /tmp/response.json

# Trigger the agent for a specific match
aws lambda invoke \
  --function-name nrl-predictor-agent \
  --payload '{"matchId": "broncos-v-raiders", "round": 12, "season": 2026}' \
  --cli-binary-format raw-in-base64-out \
  --region ap-southeast-2 \
  /tmp/response.json && cat /tmp/response.json
```

---

## Smoke-testing the API

```bash
API=https://2jjj64x7ih.execute-api.ap-southeast-2.amazonaws.com

curl $API/health
curl $API/predictions/12
curl $API/accuracy
```

A
