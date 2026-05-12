# NRL Predictor — Infrastructure Notes
## Subdomain, Cost Minimisation & Abuse Prevention

---

## 1. Subdomain Setup

Since you already have `ohare.id.au` in Route 53, this is just a DNS record addition — no new hosted zone cost.

**Route 53 change required:**
- Add a CNAME record: `nrl-predictor.ohare.id.au` → CloudFront distribution domain
- That's it. No extra $0.50/month hosted zone; it lives under the existing zone.

**Amplify custom domain:**
In the Amplify console, add `nrl-predictor.ohare.id.au` as a custom domain. Amplify will provision an ACM certificate automatically (free). It creates the required CNAME validation records — just approve them in Route 53.

---

## 2. AWS Cost Minimisation

### DynamoDB
Yes — on-demand billing means you pay per read/write unit, not per hour.
The free tier is also perpetual (not 12-month trial):
- 25 GB storage
- 25 WCU (write capacity units) / month
- 25 RCU (read capacity units) / month

For this app (8 matches × ~18 rounds, plus a few reads per page view),
you will almost certainly never leave the free tier. **DynamoDB cost: $0.**

### Lambda
Free tier: 1 million requests/month + 400,000 GB-seconds compute.
Your scrapers run maybe 20 times/week. The agent runs 8 times/round.
**Lambda cost: $0.**

### Replace Amplify with S3 + CloudFront

Amplify charges for build minutes (~$0.01/min) and has a 1000 min/month free tier,
but the ongoing per-GB-served charge adds up. For a mostly-static Next.js site,
S3 + CloudFront is cheaper:

| Component | Amplify | S3 + CloudFront |
|-----------|---------|-----------------|
| Hosting | ~$1–3/month | ~$0.02/month (S3 storage) |
| Builds | $0.01/build-min | GitHub Actions (free) |
| CDN | Included | CloudFront free tier: 1TB/month |
| Custom domain SSL | Free (ACM) | Free (ACM) |

**Trade-off:** You manage the build/deploy pipeline yourself (GitHub Actions → S3 sync).
For a personal project this is fine; for a team it's more friction.

**Recommendation for MVP:** Start with Amplify (zero config), switch to S3+CloudFront
if you find yourself paying for build minutes.

Rendering strategy: Prediction pages use ISR (Incremental Static Regeneration) with a revalidate of 300 seconds (5 minutes), matching the CloudFront cache TTL. This means Google crawls fully-rendered HTML with real prediction content, not a loading spinner. The accuracy dashboard uses SSR (no caching — always fresh). Static pages (about, how it works) are plain SSG.

```
js// app/predictions/[round]/page.tsx
export const revalidate = 300  // ISR: regenerate every 5 minutes

export default async function PredictionsPage({ params }) {
  const predictions = await getPredictions(params.round)  // fetch from DynamoDB
  // render server-side — Googlebot sees this HTML directly
}
```

### API Gateway
Free tier: 1 million API calls/month (HTTP API, not REST API — use HTTP API, it's cheaper).
**API Gateway cost: $0 at this scale.**

### Revised monthly cost estimate

| Component | Cost |
|-----------|------|
| Claude inference (Haiku dominant) | $10–25 AUD |
| Lambda | $0 |
| DynamoDB | $0 |
| S3 | < $0.10 |
| CloudFront | $0 (free tier) |
| API Gateway | $0 (free tier) |
| Route 53 (existing zone) | $0 additional |
| ACM certificate | $0 |
| **Total** | **~$10–25 AUD/month** |

The only real cost is Claude inference. Control that and you control the bill.

---

## 3. Rate Limiting — Without WAF

AWS WAF would cost ~$6–10 USD/month minimum — more than the rest of the stack combined.
Avoid it. Instead, use a layered approach with components you're already paying for.

### Layer 1: API Gateway throttling (free, stage-level)

Set on the HTTP API stage:

```
Throttle:
  Rate:  10 requests/second   (sustained)
  Burst: 20 requests           (token bucket max)

Quota (optional, per API key):
  500 requests/day
```

This caps runaway traffic at the API level before Lambda is even invoked.
Configure in the API Gateway console under "Default route throttling".

**Limitation:** This is per-stage (all users share the bucket), not per-IP.
Good enough for a personal site.

### Layer 2: Per-IP rate limiting in Lambda (free, uses DynamoDB)

Add a rate-limit check at the top of your Lambda handler:

```python
import boto3
import json
import time
from datetime import datetime, timezone

dynamodb = boto3.resource("dynamodb")
rate_table = dynamodb.Table("rate_limits")

HOURLY_LIMIT = 20   # requests per IP per hour
DAILY_LIMIT  = 100  # requests per IP per day

def check_rate_limit(ip: str) -> tuple[bool, str]:
    """Returns (allowed: bool, reason: str)."""
    now = int(time.time())
    hour_key = f"{ip}#hour#{now // 3600}"
    day_key  = f"{ip}#day#{now // 86400}"

    # Atomic increment for hour bucket
    try:
        hour_resp = rate_table.update_item(
            Key={"pk": hour_key},
            UpdateExpression="ADD #cnt :one SET #ttl = if_not_exists(#ttl, :ttl)",
            ExpressionAttributeNames={"#cnt": "count", "#ttl": "ttl"},
            ExpressionAttributeValues={":one": 1, ":ttl": now + 7200},
            ReturnValues="UPDATED_NEW",
        )
        hour_count = int(hour_resp["Attributes"]["count"])
    except Exception:
        return True, "ok"  # fail open — don't block if DynamoDB is down

    if hour_count > HOURLY_LIMIT:
        return False, f"Rate limit exceeded: {HOURLY_LIMIT} requests/hour"

    # Increment day bucket
    day_resp = rate_table.update_item(
        Key={"pk": day_key},
        UpdateExpression="ADD #cnt :one SET #ttl = if_not_exists(#ttl, :ttl)",
        ExpressionAttributeNames={"#cnt": "count", "#ttl": "ttl"},
        ExpressionAttributeValues={":one": 1, ":ttl": now + 172800},
        ReturnValues="UPDATED_NEW",
    )
    day_count = int(day_resp["Attributes"]["count"])

    if day_count > DAILY_LIMIT:
        return False, f"Rate limit exceeded: {DAILY_LIMIT} requests/day"

    return True, "ok"


def lambda_handler(event, context):
    ip = (event.get("requestContext", {})
              .get("http", {})
              .get("sourceIp", "unknown"))

    allowed, reason = check_rate_limit(ip)
    if not allowed:
        return {
            "statusCode": 429,
            "headers": {
                "Content-Type": "application/json",
                "Retry-After": "3600",
            },
            "body": json.dumps({"error": reason}),
        }

    # ... rest of handler
```

**DynamoDB table for rate_limits:**
- Partition key: `pk` (string)
- TTL attribute: `ttl` (number) — enable TTL in DynamoDB console
  → records auto-delete after expiry; no manual cleanup needed
- Billing: on-demand; at this scale, cost rounds to $0

### Layer 3: CloudFront Function for bot blocking (free)

CloudFront Functions run at the edge before the request hits API Gateway.
The free tier covers 2 million invocations/month.

Create a CloudFront Function and associate it with your distribution's
`viewer-request` event:

```javascript
function handler(event) {
    var request = event.request;
    var ua = (request.headers['user-agent']
              ? request.headers['user-agent'].value
              : '').toLowerCase();

    // Explicitly allow legitimate search crawlers
    var allowedCrawlers = ['googlebot', 'bingbot', 'slurp', 'duckduckbot'];
    for (var i = 0; i < allowedCrawlers.length; i++) {
        if (ua.indexOf(allowedCrawlers[i]) !== -1) {
            return request;  // pass through immediately
        }
    }

    // Block everything else that looks automated
    var blockedPatterns = [
        'python-requests', 'curl/', 'wget/', 'scrapy',
        'go-http-client', 'java/', 'okhttp', 'httpclient',
        'semrush', 'ahrefs', 'mj12bot', 'dotbot',
        'gptbot', 'ccbot', 'anthropic-ai',
    ];

    for (var i = 0; i < blockedPatterns.length; i++) {
        if (ua.indexOf(blockedPatterns[i]) !== -1) {
            return {
                statusCode: 403,
                statusDescription: 'Forbidden',
                body: 'Automated access is not permitted.',
            };
        }
    }

    // Block empty or suspiciously short User-Agents
    if (!ua || ua.length < 10) {
        return {
            statusCode: 403,
            statusDescription: 'Forbidden',
            body: 'Invalid request.',
        };
    }

    return request;
}
```

**Note:** This catches naive bots and scrapers. A determined scraper with
a browser User-Agent will get through — but that's fine, the Lambda-level
rate limiter handles that case anyway.

### Layer 4: robots.txt (served from S3/public folder)

Place in your site's `public/` directory:

```
# Welcome search engines
User-agent: Googlebot
Allow: /
Disallow: /api/

User-agent: Bingbot
Allow: /
Disallow: /api/

# Block AI training crawlers
User-agent: GPTBot
Disallow: /

User-agent: CCBot
Disallow: /

User-agent: anthropic-ai
Disallow: /

User-agent: Google-Extended
Disallow: /

# Everyone else: pages yes, API no
User-agent: *
Disallow: /api/

Crawl-delay: 10
```

Disallow the API routes entirely. The front-end content pages can be
indexed if you want (good for SEO eventually), but the API endpoints
should never be crawled.

### Summary: defence-in-depth without WAF

```
Internet
   ↓
CloudFront Function   ← blocks bot User-Agents, empty UA  (free)
   ↓
CloudFront cache      ← prediction pages cached 5min; many requests
                         never reach Lambda at all              (free)
   ↓
API Gateway           ← stage-level throttle: 10 rps / 20 burst (free)
   ↓
Lambda                ← per-IP hourly/daily limit via DynamoDB  (free)
   ↓
Claude API            ← spend limit set in Anthropic Console
```

---

## 4. Claude API Spend Limits

### Anthropic Console (hard cap)

1. Go to [console.anthropic.com](https://console.anthropic.com)
2. Settings → Billing → Usage limits
3. Set a **monthly spend limit** — e.g. $20 USD
4. Anthropic will stop accepting API requests once the limit is hit
   (returns a 529 error)
5. Also set an **email alert threshold** — e.g. alert at $10 USD so you
   get warning before the hard cap hits

This is your primary protection.

### Application-level token budget (belt and braces)

Implement a monthly spend tracker in DynamoDB:

```python
# In your prediction Lambda, after generating a prediction:
import boto3
from datetime import datetime

MONTHLY_BUDGET_USD = 18.0   # stop slightly below Anthropic's hard cap
HAIKU_INPUT_PER_1K  = 0.00025   # USD per 1K input tokens (Haiku 3.5)
HAIKU_OUTPUT_PER_1K = 0.00125   # USD per 1K output tokens

def record_usage_and_check_budget(input_tokens: int, output_tokens: int) -> bool:
    """
    Records token usage and returns False if monthly budget exceeded.
    """
    cost_usd = (
        (input_tokens  / 1000) * HAIKU_INPUT_PER_1K +
        (output_tokens / 1000) * HAIKU_OUTPUT_PER_1K
    )
    month_key = datetime.utcnow().strftime("%Y-%m")

    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table("claude_usage")

    resp = table.update_item(
        Key={"pk": f"monthly#{month_key}"},
        UpdateExpression="ADD cost_usd :cost, input_tokens :inp, output_tokens :out",
        ExpressionAttributeValues={
            ":cost": str(round(cost_usd, 6)),  # DynamoDB doesn't do float ADD cleanly
            ":inp":  input_tokens,
            ":out":  output_tokens,
        },
        ReturnValues="UPDATED_NEW",
    )

    # Note: use Decimal for DynamoDB numeric ADD — adjust as needed
    current_spend = float(resp["Attributes"].get("cost_usd", 0))
    if current_spend >= MONTHLY_BUDGET_USD:
        # Alert via CloudWatch metric / SNS
        cloudwatch = boto3.client("cloudwatch")
        cloudwatch.put_metric_data(
            Namespace="NRLPredictor",
            MetricData=[{
                "MetricName": "BudgetExceeded",
                "Value": 1,
                "Unit": "Count",
            }]
        )
        return False   # caller should skip Claude call and serve cached/placeholder
    return True
```

**DynamoDB `claude_usage` table:**
- Partition key: `pk` (string)  e.g. `monthly#2026-05`
- No TTL needed — keep records for cost audit trail

Verify SSR/ISR is working: curl https://nrl-predictor.ohare.id.au/predictions/12 should return prediction content in the raw HTML, not a loading state. Check with curl rather than a browser to confirm.


One Amplify gotcha worth knowing: Amplify fully supports Next.js SSR — it spins up a Lambda behind the scenes for server-rendered pages. Just make sure you're deploying as an SSR app (the default when Amplify detects Next.js with server components), not as a static export. If you ever add output: 'export' to next.config.js for any reason, SSR breaks and Googlebot gets the empty shell. Leave that option out.

### CloudWatch alarm for spend

Create a CloudWatch alarm on the `BudgetExceeded` metric that sends
an SNS email/SMS when it fires. Cheap insurance.

---

## 5. Updated Architecture Diagram

```
nrl-predictor.ohare.id.au  (Route 53 CNAME → CloudFront)
        │
        ▼
┌─────────────────────────────────────────────────────┐
│  CloudFront Distribution                            │
│  ├── /          → S3 bucket (static Next.js)        │
│  ├── /api/*     → API Gateway (HTTP API)            │
│  └── CloudFront Function: bot UA blocking           │
└─────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────┐     ┌─────────────────────────────┐
│  API Gateway    │     │  EventBridge Scheduler      │
│  (HTTP API)     │     │  Thu/Fri/Sat cron jobs       │
│  Throttle:      │     └──────────────┬──────────────┘
│  10 rps / 20b   │                    │
└────────┬────────┘                    │
         │                             ▼
         ▼                    ┌────────────────────┐
┌─────────────────┐           │  Scraper Lambdas   │
│  API Lambda     │           │  nrl / bom /       │
│  - IP rate limit│           │  articles          │
│  - Serve        │           └────────┬───────────┘
│    predictions  │                    │
└────────┬────────┘                    ▼
         │             ┌───────────────────────────────┐
         │             │  DynamoDB Tables               │
         └────────────▶│  predictions / teams /         │
                       │  results / metrics /           │
                       │  rate_limits / claude_usage    │
                       └──────────────┬────────────────┘
                                      │
                              ┌───────▼────────┐
                              │  Agent Lambda  │
                              │  (LangGraph)   │
                              │  - budget check│
                              └───────┬────────┘
                                      │
                              ┌───────▼────────┐
                              │  Anthropic API │
                              │  Claude Haiku  │
                              │  (spend limit  │
                              │   in Console)  │
                              └────────────────┘
```
