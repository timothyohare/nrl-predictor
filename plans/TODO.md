# New Projects TODO

## Explore alternative prediction targets
- [ ] Research horse racing data sources (Racing.com, TAB API, form guides)
- [ ] Research tennis data sources (ATP/WTA stats, Tennis Abstract, SportRadar)
- [ ] Evaluate BBL/cricket as a high-frequency prediction target
- [ ] Decide on primary alternative domain (horse racing vs tennis vs cricket)
- [ ] Confirm API keys / data source availability for chosen domain

## NRL Predictor v2 — LangGraph multi-agent
See: [`01_nrl_langgraph_multi_agent.md`](01_nrl_langgraph_multi_agent.md)

- [ ] Create new GitHub repo: `nrl-predictor-v2`
- [ ] Set up Python project with LangChain + LangGraph + same dev/test tooling
- [ ] Port existing scrapers (draw, team-sheets, weather, articles, odds) as-is
- [ ] Design LangGraph StateGraph: Router → Primary → Challenger → Judge → Extended
- [ ] Implement Difficulty Router node (classifies match as EASY / CONTESTED / COMPLEX)
- [ ] Implement Primary Predictor (Haiku for EASY, Sonnet for CONTESTED/COMPLEX)
- [ ] Implement Challenger node (devil's advocate pushback)
- [ ] Implement Synthesis Judge (weighs primary + challenger → final prediction)
- [ ] Implement Extended Predictor node (first try scorer, margin bracket, player props)
- [ ] Write tool layer with LangChain tools wrapping existing DynamoDB-backed logic
- [ ] Set up CDK infra for new Lambda + Step Functions (or LangGraph server)
- [ ] Deploy and run shadow predictions against v1 for calibration
- [ ] Add agent trace/decision logging table to DynamoDB

## Horse Racing multi-agent predictor
See: [`02_horse_racing_agent.md`](02_horse_racing_agent.md)

- [ ] Spike Racing.com / TAB API to assess data availability
- [ ] Spike punters.com.au form guide scraping
- [ ] Create new GitHub repo: `racing-predictor`
- [ ] Build Form Analyst agent (last-10-start normalisation + sectionals)
- [ ] Build Track & Conditions agent (track rating, barrier bias, rail position)
- [ ] Build Market Intelligence agent (odds drift / smart-money detection)
- [ ] Build Judge synthesis agent
- [ ] Set up daily cron to pull race cards + run predictions
- [ ] Build scoring / calibration pipeline (results ~10 mins after race)
- [ ] Front end or Slack bot for outputs

## Tennis tournament multi-agent predictor
See: [`03_tennis_predictor.md`](03_tennis_predictor.md)

- [ ] Spike ATP/WTA stats API and Tennis Abstract data availability
- [ ] Create new GitHub repo: `tennis-predictor`
- [ ] Build Stats Analyzer agent (surface win rates, serve/return metrics)
- [ ] Build Form & Momentum agent (recent form curve, fatigue index)
- [ ] Build Matchup Specialist agent (H2H, playing-style compatibility)
- [ ] Build Upset Detector agent (structural advantage identification)
- [ ] Build Judge synthesis agent (match result + set score prediction)
- [ ] Set up pre-tournament and pre-match cron runs
- [ ] Build scoring pipeline (results available live via API)

## Shared infrastructure
- [ ] Extract common LangGraph agent scaffolding into a shared library (`agentic-core`)
- [ ] Set up shared AWS account structure / IAM roles for new projects
- [ ] Document which API keys are reusable (Anthropic, Tavily, The Odds API)
- [ ] Create Amplify / CloudFront front end template for prediction dashboards
