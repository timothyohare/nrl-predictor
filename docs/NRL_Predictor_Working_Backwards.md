# NRL Predictor
**AI-Powered Match Predictions for the National Rugby League**

*Working Backwards PR/FAQ | Technical Specification | Delivery Plan*

| Author | Tim O'Hare | Date | May 2026 |
|--------|-----------|------|----------|

---

## Section 1 — Press Release

**FOR IMMEDIATE RELEASE**
Sydney, Australia

---

### NRL Predictor Brings AI-Powered Match Intelligence to Rugby League Fans

*New platform synthesises team sheets, injuries, form, weather and expert analysis to generate transparent, reasoned match predictions — updated automatically as late changes emerge.*

Rugby league fans in Australia have always debated who will win on the weekend. But those debates have never had access to the same quality of synthesised information that professional analysts, coaches and punters use. NRL Predictor changes that.

NRL Predictor is a free, web-based platform that reads official team sheets the moment they are published, cross-references injury lists, checks weather forecasts at the venue, analyses recent form and then generates a clear, readable prediction for every match of the round — complete with the reasoning behind it.

Unlike traditional tipping tools that rely solely on historical statistics or simple ladder position, NRL Predictor uses a multi-source AI research agent to reason through each game the way an experienced analyst would. When a star halfback is ruled out on Friday afternoon, the prediction updates. When conditions are forecast to be wet and windy, the model adjusts its expectation of high-scoring, open play.

> **Key Feature:** Every prediction comes with a full written explanation — not just a winner and a margin, but why the AI landed on that call, which factors were decisive, and how confident it is. Users can read the reasoning and make their own judgement.

The platform tracks its own accuracy round by round and season by season, publishing a transparent performance dashboard so fans can evaluate whether the predictions are genuinely useful. The system re-runs predictions automatically when official team sheets drop on Friday, so predictions are always based on the most current available information.

NRL Predictor is built on AWS, powered by Anthropic's Claude AI, and designed for Australian rugby league fans who want smarter, more transparent predictions — without the paywall.

> *"We wanted to build something that reasons out loud. Most tipping sites give you a number. We give you the analysis behind the number — and we publish our track record so you can decide if it's worth reading."*
> — Founder

NRL Predictor launches ahead of the 2026 NRL Finals Series and will cover all 16 teams across every round of the remaining season and beyond.

**Visit: nrl-predictor.ohare.id.au**

---

## Section 2 — FAQ

### Customer FAQs

**Q: What exactly does NRL Predictor do?**

For every NRL match each round, the platform reads the official team sheets (published Thursday/Friday), injury reports, recent form, venue, weather and other contextual factors. An AI research agent synthesises all of this into a prediction — a winner, estimated margin, confidence level and a written explanation of the reasoning. Predictions are updated automatically if late changes are published before kick-off.

---

**Q: How is this different from other tipping sites?**

Most tipping sites use historical win/loss records or ELO ratings, which are good at capturing long-run team quality but cannot react to information published two days before a game. NRL Predictor is designed specifically around late-breaking information — the team sheet published Friday, the player ruled out Saturday morning. The AI reads and reasons about this in near real-time. It also shows its reasoning, not just its answer.

---

**Q: How accurate is it?**

We publish our full accuracy record on the platform: season-to-date correct picks, average margin error, and calibration of confidence levels (i.e. when we say 70% confident, are we right about 70% of the time?). NRL is notoriously unpredictable. A 60–65% correct pick rate across a full season is respectable; we aim to be well-calibrated rather than overconfident. You can see exactly how we have performed every week.

---

**Q: Does it cost anything?**

No. The platform is free. We may introduce an optional supporter tier in the future for users who want round-summary emails or push notifications, but core predictions will remain free.

---

**Q: When are predictions published each round?**

A first-pass prediction is generated mid-week once the round draw is confirmed. This updates on Thursday night and Friday when official 17s are lodged. A final update runs Saturday morning to catch any late withdrawals. The site always shows a timestamp for when each prediction was last generated.

---

**Q: What factors does the AI consider?**

Team sheet quality (who is playing vs who is out), recent form (last 5 games), head-to-head record at the venue, home/away advantage, travel burden, weather (particularly for kicking-game teams), referee assignment tendencies, and contextual analysis from credible rugby league journalists.

---

### Internal / Technical FAQs

**Q: Why use a GenAI agent rather than a trained prediction model?**

Trained ML models require labelled historical data and are static between training runs. They cannot ingest a PDF team sheet published 48 hours before kick-off and adjust their prediction accordingly. GenAI agents can read arbitrary text, reason about its implications, and synthesise it with structured data in real time. The freshness of information is the core advantage.

---

**Q: What is the inference cost per round?**

Using Claude Haiku 3.5 for most tool calls and document summarisation, with Haiku or Sonnet for final synthesis: estimated $0.10–$0.30 AUD per match at current pricing, or roughly $1–$5 per full round of 8 games. Costs scale with the number of data sources and re-runs for late changes. A weekly budget of $10 AUD is ample for the full system.

---

**Q: How does performance tracking work?**

After each match, a Lambda function fetches the final score from the NRL API and compares it against the stored prediction. Results are written to a DynamoDB predictions table. A weekly aggregation job computes accuracy metrics per round, per team and season-to-date. These metrics power a public dashboard. Brier scores are computed for calibration tracking.

---

**Q: What is the data pipeline?**

EventBridge cron rules trigger Lambda scrapers (Thu/Fri/Sat) that fetch team sheets, injury lists and related text. Structured data is stored in DynamoDB; raw text and articles are stored in S3. The LangGraph agent is invoked per match, using DynamoDB/S3 as tool backends and optionally calling a web search tool for breaking news. Predictions are stored as JSON in DynamoDB and rendered via a Next.js front end served at `nrl-predictor.ohare.id.au`.

---

**Q: How do we prevent hallucinated player names or statistics?**

All statistical claims in the prompt are grounded in scraped data retrieved by tools — the agent does not rely on its parametric memory for current-season facts. The prompt explicitly instructs the model to cite the source of each claim and flag uncertainty where data is missing. A post-processing validation step checks that named players appear on the retrieved team sheet before the prediction is published.

---

**Q: What is the scaling strategy?**

The system is fully serverless. Lambda functions scale automatically. DynamoDB is on-demand billing. Amplify scales the front end. Rate limiting uses DynamoDB TTL counters — no Redis or ElastiCache required.

---

## Section 3 — Technical Specification

### 3.1 System Overview

NRL Predictor is a serverless, event-driven AWS application. A scraping layer collects raw data from public sources on a schedule. A LangGraph-based AI agent processes and synthesises this data into structured predictions. A Next.js front end hosted on Amplify presents predictions and a performance dashboard to users.

> **Design Principle:** Every component is stateless and event-driven. The system must handle the NRL's irregular schedule (Thursday night games, Sunday afternoon, State of Origin interruptions) through configuration, not code changes.

---

### 3.2 Data Sources

| Source | Data Extracted | Method |
|--------|---------------|--------|
| nrl.com | Team sheets, draw, ladder, results, player profiles | HTML scrape / unofficial JSON API |
| NRL club sites | Injury lists, late changes, media releases | HTML scrape per club |
| BOM (Bureau of Meteorology) | Venue weather forecast (rain, wind, temp) | BOM API / JSON feeds |
| Zero Tackle / The Roar | Journalist analysis and tips (text) | HTML scrape, article extraction |
| SuperCoach / Fantasy NRL | Price movements as proxy for team sheet changes | HTML scrape |
| NRL Stats API | Historical head-to-head, season stats | REST API (where available) |

---

### 3.3 AWS Architecture

#### Compute

- AWS Lambda: all scraping, agent orchestration, post-match scoring and aggregation
- Lambda function memory: 512 MB for scrapers, 1 GB for LangGraph agent (5-minute timeout)
- LangGraph agent runs as a single Lambda invocation per match; parallel invocations for simultaneous games

#### Storage

- **Amazon DynamoDB** — primary data store
  - Table: `predictions` — partition key: `matchId`, sort key: `generatedAt` (ISO timestamp)
  - Table: `teams` — current season roster, injury flags, updated per scrape
  - Table: `results` — final scores, used for accuracy computation
  - Table: `metrics` — pre-aggregated accuracy stats per round and season
  - Table: `rate_limits` — per-IP hourly/daily request counters; TTL auto-expiry
  - Table: `claude_usage` — monthly token and spend tracking for budget enforcement
- **Amazon S3** — raw scraped HTML and article text, stored with TTL metadata for cache decisions

#### Scheduling

- Amazon EventBridge Scheduler: cron-based triggers per scraping run
- Round scrape schedule: Wednesday 18:00, Thursday 22:00 (after Thu team sheets), Friday 14:00, Friday 22:00, Saturday 08:00
- Post-match scoring: triggered 90 minutes after scheduled kick-off via EventBridge

#### Front End

- AWS Amplify: hosts Next.js application, CDN distribution, CI/CD from GitHub
- Custom domain: `nrl-predictor.ohare.id.au` — CNAME added to existing Route 53 hosted zone; ACM certificate provisioned automatically by Amplify (no extra hosted zone cost)
- API Gateway + Lambda: serves prediction JSON to front end
- CloudFront: 5-minute TTL on prediction endpoints to avoid redundant Lambda invocations

**Rendering strategy:**

| Page | Strategy | Reason |
|------|----------|--------|
| Predictions (round view) | ISR — `revalidate: 300` | Matches CloudFront TTL; Googlebot sees fully-rendered prediction HTML |
| Accuracy dashboard | SSR | Always fresh — never serve stale accuracy stats |
| Static pages (about, how it works) | SSG | Build-time only; no server cost |

Do not add `output: 'export'` to `next.config.js` — this switches Next.js to a static export and breaks SSR/ISR, causing Googlebot to receive an empty shell instead of rendered predictions.

#### Observability

- AWS CloudWatch: Lambda logs, custom metrics for scrape success/failure rates
- CloudWatch Alarms: alert on scraper failures within 30 minutes of scheduled run
- AWS X-Ray: trace LangGraph agent tool calls for latency analysis

---

### 3.4 LangGraph Agent Design

The agent follows a ReAct (Reason + Act) pattern. For each match, the agent:

1. Receives a match context object: teams, venue, date, round
2. Plans which tools to call to gather sufficient evidence
3. Calls tools in sequence (or parallel where independent)
4. Reassesses evidence and identifies gaps
5. Generates a structured prediction with reasoning
6. Validates that named players exist on the retrieved team sheet

#### Tools Available to Agent

| Tool | Description |
|------|-------------|
| `get_team_sheet(team, round)` | Returns the official 1–17 + bench for the specified team and round from DynamoDB |
| `get_injury_list(team)` | Returns current injury/unavailability list for the team |
| `get_recent_form(team, n)` | Returns last n match results with score, venue, opposition |
| `get_head_to_head(team_a, team_b, venue)` | Historical record between two teams at the specified venue |
| `get_weather(venue, date)` | BOM forecast for venue on match date (rain probability, wind speed, temp) |
| `get_ladder()` | Current season ladder with points, for/against, percentage |
| `search_articles(query)` | Searches S3 corpus of scraped articles for relevant text chunks |
| `web_search(query)` | Live web search for breaking news not yet in the corpus |

#### Model Selection Strategy

Cost optimisation uses a tiered approach:

- **Tool calls and document summarisation:** Claude Haiku 3.5 — fast, cheap, sufficient for structured extraction
- **Final prediction synthesis:** Claude Haiku 3.5 for standard rounds; Claude Sonnet 4 for finals, derbies and close-line games
- **Late-change re-run:** Haiku for re-assessment; Sonnet only if the change is classified as high-impact (e.g. halfback, hooker or starting prop removed from team sheet)

#### Prediction Output Schema

The agent is instructed to return a JSON object conforming to:

| Field | Type | Description |
|-------|------|-------------|
| `predicted_winner` | string | Team name |
| `predicted_margin` | integer | Points (0 if too close to call) |
| `confidence` | string | LOW / MEDIUM / HIGH |
| `key_factors` | string[] | 2–4 decisive factors in plain English |
| `reasoning` | string | 200–400 word analyst-style explanation |
| `data_freshness` | string | ISO timestamp of most recent team sheet used |
| `model_used` | string | claude-haiku-4-5 or claude-sonnet-4-6 |
| `generated_at` | string | ISO timestamp of prediction generation |

---

### 3.5 Performance Tracking System

This is a first-class feature, not an afterthought. The system is designed to be honest about its own accuracy and to surface that information prominently.

#### Post-Match Scoring

A Lambda function fires 90 minutes after each match's scheduled kick-off. It:

1. Fetches the final score from the NRL results API
2. Loads the most recent prediction from DynamoDB
3. Computes: `correct_pick` (bool), `predicted_margin_error` (int), `within_6_pts` (bool), `within_12_pts` (bool)
4. Computes Brier score component for the match based on confidence level mapped to probability
5. Writes result record to the `results` table
6. Triggers the metrics aggregation function

#### Metrics Aggregated

| Metric | Granularity | Purpose |
|--------|------------|---------|
| Correct pick rate | Round, season, team, home/away | Primary accuracy measure |
| Mean absolute margin error | Round, season | How far off the predicted margin is |
| Brier score | Season | Calibration: are confidence levels honest? |
| Pick rate by confidence tier | Season | Do HIGH confidence tips outperform LOW? |
| Upset detection rate | Season | How often do we call the underdog correctly? |
| Team-specific accuracy | Per team, season | Which teams are we best/worst at predicting? |
| Late change sensitivity | Season | Do re-runs after team sheet changes improve accuracy? |

#### Public Dashboard

The front end includes a dedicated Accuracy page showing:

- Season-to-date scorecard (correct picks / total, %)
- Round-by-round bar chart of accuracy
- Confidence calibration chart (predicted confidence vs actual accuracy)
- Team accuracy heat map (which teams we tip well vs poorly)
- "This round" prediction table with outcomes filled in as matches complete

> **Honesty Principle:** The accuracy dashboard is always visible and never hidden when performance is poor. If the system is performing below 50%, that is displayed prominently. Credibility comes from transparency.

---

### 3.6 Abuse Prevention & Spend Controls

Protection is layered so that no single component carries the full burden, and no component costs money beyond what is already in the stack.

#### Defence layers (outermost to innermost)

**1. robots.txt** — served from the Next.js `public/` folder:
- Googlebot and Bingbot: allowed on all pages, blocked from `/api/`
- AI training crawlers (GPTBot, CCBot, Google-Extended, anthropic-ai): fully blocked
- All other bots: pages allowed, `/api/` blocked
- `Crawl-delay: 10`

**2. CloudFront Function** (free — 2M invocations/month included):
- Runs on every `viewer-request` before the request reaches API Gateway
- Explicitly passes through known search crawler User-Agents (googlebot, bingbot, slurp, duckduckbot)
- Blocks known scraper patterns: python-requests, curl, wget, scrapy, go-http-client, AI crawlers
- Blocks empty or suspiciously short User-Agents (< 10 chars)
- Returns 403 at edge — Lambda is never invoked, so no cost

**3. API Gateway stage throttling** (free, built-in):
- Rate: 10 requests/second sustained
- Burst: 20 requests (token bucket)
- Applies across all users; prevents runaway traffic from reaching Lambda

**4. Per-IP rate limiting in Lambda** (free — uses DynamoDB TTL counters):
- 20 requests per IP per hour
- 100 requests per IP per day
- Counters stored in `rate_limits` DynamoDB table with TTL auto-expiry
- Returns 429 with `Retry-After: 3600` header
- Fails open (passes request) if DynamoDB is unavailable — never blocks legitimate traffic due to infrastructure issues

#### Claude API spend controls

**Anthropic Console hard cap:**
- Set monthly spend limit in Console → Settings → Billing → Usage limits (e.g. $20 USD)
- Anthropic returns 529 once the cap is hit — no further charges possible
- Set an email alert at ~50% of cap for early warning

**Application-level budget tracker:**
- Every Claude API call records input/output token counts to the `claude_usage` DynamoDB table
- Lambda checks estimated month-to-date spend before invoking Claude
- If spend exceeds the configured threshold (set slightly below the Anthropic cap), Lambda skips the Claude call and serves the most recent cached prediction with a staleness flag
- CloudWatch alarm fires on a `BudgetExceeded` custom metric

---

## Section 4 — Delivery Plan

### 4.1 Phases

#### Phase 1 — Data Foundation (Weeks 1–2)

Goal: reliable, scheduled data collection running in AWS.

- Set up AWS account structure: IAM roles, DynamoDB tables (`predictions`, `teams`, `results`, `metrics`), S3 bucket (`raw-scrapes`)
- Build and deploy Lambda scrapers: nrl.com team sheets, ladder, draw
- Add injury/late-changes scraper (club sites or aggregator)
- Add BOM weather scraper (venue lookup by postcode)
- EventBridge schedule: Wed/Thu/Fri/Sat cron triggers
- CloudWatch alarms for scraper failures
- Manual test run: verify all 8 matches for a round have complete data

#### Phase 2 — Agent MVP (Weeks 3–4)

Goal: end-to-end prediction for a single match, running locally.

- Build LangGraph graph: nodes for each tool, ReAct orchestrator, output parser
- Implement all 8 tools backed by DynamoDB/S3
- Write and iterate on system prompt: analyst persona, reasoning chain instructions, JSON output schema
- Add player validation post-processing step
- Run predictions against historical rounds with known outcomes — evaluate qualitatively
- Tune prompt for reasoning quality; identify where agent skips important factors

#### Phase 3 — Automation and Scoring (Week 5)

Goal: fully automated weekly loop.

- Deploy LangGraph agent as Lambda function (5-minute timeout)
- Wire EventBridge to invoke agent per match after Friday team sheets drop
- Build post-match scoring Lambda: fetch result, compare vs prediction, write to `results` table
- Build metrics aggregation Lambda: compute all accuracy metrics, write to `metrics` table
- End-to-end test: verify full cycle runs for a complete round

#### Phase 4 — Front End (Weeks 6–7)

Goal: public website with predictions and accuracy dashboard.

- Scaffold Next.js application on AWS Amplify
- Predictions page: round selector, match cards showing winner, margin, confidence, key factors, full reasoning (expandable)
- Accuracy page: season scorecard, round-by-round chart, confidence calibration chart, team heat map
- Mobile-responsive layout
- Round complete banner: fills in actual results next to predictions once matches finish
- Late-change badge: highlights predictions that were re-generated after team sheet changes
- Implement ISR (`revalidate: 300`) on prediction pages, SSR on accuracy dashboard, SSG on static pages
- Verify rendering: `curl https://nrl-predictor.ohare.id.au/predictions/12` must return prediction content in raw HTML — not a loading state

#### Phase 5 — Hardening and Launch (Week 8)

Goal: production-ready and publicly accessible.

- Add CNAME record `nrl-predictor.ohare.id.au` to existing Route 53 hosted zone (no new hosted zone required)
- Configure Amplify custom domain; ACM certificate provisioned automatically
- CloudFront distribution with 5-minute prediction cache
- Deploy CloudFront Function for bot User-Agent blocking; verify Googlebot passes through
- Add `robots.txt` to `public/` folder; verify with Google Search Console after launch
- Configure API Gateway stage throttling (10 rps / 20 burst)
- Set Anthropic Console monthly spend limit and 50% alert threshold
- Load test: verify Amplify/API Gateway handles concurrent users during peak (Saturday morning)
- Implement retry logic in scrapers for flaky sources
- Final round of prediction quality review against live team sheets
- Soft launch: share with a small group for feedback before promoting publicly

---

### 4.2 Technology Stack Summary

| Layer | Technology |
|-------|-----------|
| AI Inference | Anthropic Claude (Haiku 3.5 primary, Sonnet 4 for finals/high-impact) |
| Agent Framework | LangGraph (Python) |
| Compute | AWS Lambda (Python 3.12) |
| Scheduling | Amazon EventBridge Scheduler |
| Database | Amazon DynamoDB (on-demand) |
| Object Storage | Amazon S3 (raw scrapes) |
| Front End Framework | Next.js 15 (App Router) |
| Front End Hosting | AWS Amplify |
| CDN / Cache | Amazon CloudFront |
| API Layer | Amazon API Gateway + Lambda |
| Observability | CloudWatch Logs, Metrics, Alarms; AWS X-Ray |
| DNS | Amazon Route 53 |
| Source Control | GitHub |
| CI/CD | Amplify Git integration (front end); GitHub Actions (Lambda deploys) |

---

### 4.3 Cost Estimate (Monthly, AUD)

| Component | Estimated Cost | Notes |
|-----------|---------------|-------|
| Claude inference | $10–25 / month | ~8 matches × ~18 rounds + re-runs, mixed Haiku/Sonnet |
| Lambda | $0 | Well within perpetual free tier for invocation volume |
| DynamoDB | $0 | Perpetual free tier: 25 WCU / 25 RCU / 25 GB — more than sufficient |
| S3 | < $0.10 / month | Raw HTML storage, small volume |
| Amplify | $0–3 / month | Free tier covers hobby-scale traffic and build minutes |
| CloudFront | $0 | Free tier: 1 TB/month data transfer |
| API Gateway | $0 | Free tier: 1M HTTP API calls/month |
| Route 53 | $0 additional | Subdomain added to existing ohare.id.au hosted zone |
| ACM certificate | $0 | Provisioned automatically by Amplify |
| **Total** | **~$10–28 AUD/month** | **Dominated by Claude inference cost** |

---

### 4.4 Risks and Mitigations

| Risk | Likelihood | Mitigation |
|------|-----------|-----------|
| nrl.com changes HTML structure | Medium | Abstract scraper into configurable selectors; CloudWatch alarm on parse failures |
| Scraper blocked / rate limited | Low–Medium | Randomised delays, User-Agent rotation; fall back to cached data if blocked within 12 hrs of kick-off |
| Agent hallucinates player statistics | Medium | All stats grounded in tool output; player name validation against retrieved team sheet |
| NRL API goes down pre-game | Low | S3 fallback cache of last successful scrape; front end shows data freshness timestamp |
| Accuracy is persistently poor | Medium | Publish it honestly; adjust prompt and data sources; document changes publicly |
| Claude API rate limits hit during mass re-run | Low | Stagger invocations with EventBridge delays; Haiku has generous throughput limits |
| Abusive traffic exhausts Claude budget | Low | CloudFront Function blocks bots at edge; per-IP Lambda rate limit; Anthropic Console hard spend cap |
| Claude spend cap hit mid-round | Low | Application-level budget tracker serves cached prediction with staleness flag; CloudWatch alarm fires |

---

### 4.5 Success Criteria at Launch

- All 8 matches predicted by Saturday 09:00 AEST, every round
- Predictions always based on team sheets published within the last 18 hours
- Post-match accuracy computed and displayed within 4 hours of final whistle
- Season-to-date correct pick rate visible on front page
- Zero published predictions containing a player not on the retrieved team sheet
- Total monthly AWS + inference cost below $30 AUD

> **North Star Metric:** A user reads our prediction reasoning and says "I hadn't thought of that" — and then goes and checks the team sheet themselves. We win when we make fans smarter, not just when we pick the winner.

---

*— End of Document —*
