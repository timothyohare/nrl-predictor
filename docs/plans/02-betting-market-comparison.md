# Plan: Betting Market Comparison (Phase 8)

## Goal

Compare our AI predictions against betting market odds to find outliers — matches where our prediction disagrees with the market. Track market accuracy using the same metrics as our predictions (correct pick, margin error, Brier score). The betting odds must NOT be used as an input to the prediction agent.

## Constraint (add to CLAUDE.md)

> Betting market odds are tracked for comparison purposes only. They must NEVER be used as input to the prediction agent. The predictions must remain independent so the comparison is meaningful.

## Data Source

**the-odds-api.com** — free tier: 500 requests/month (we need ~16/week: 8 matches × 2 for pre-match + live close).

- Endpoint: `GET /v4/sports/rugbyleague_nrl/odds`
- Returns: head-to-head (moneyline) and spreads (line/margin) from multiple bookmakers
- API key stored in Secrets Manager: `nrl-predictor/odds-api-key`

Alternative: direct scrape of Sportsbet/TAB odds pages (more fragile, no API key needed).

## New AWS Resources

### DynamoDB table: `odds`

| Field | Type | Description |
|-------|------|-------------|
| `matchId` (PK) | String | Same matchId format as predictions |
| `scrapedAt` (SK) | String | ISO timestamp |
| `market_favourite` | String | Team nickname favoured by the market |
| `market_margin` | Number | Spread/line (positive = favourite's expected margin) |
| `home_odds` | Number | Decimal odds for home win |
| `away_odds` | Number | Decimal odds for away win |
| `bookmaker` | String | Source bookmaker (e.g. "sportsbet", "tab", "average") |
| `implied_home_prob` | Number | 1/home_odds normalised |
| `implied_away_prob` | Number | 1/away_odds normalised |
| `season` | Number | |
| `roundNumber` | Number | |

### Secrets Manager

- `nrl-predictor/odds-api-key` — the-odds-api.com API key

## Implementation Steps

### 1. [TEST] Write `tests/scrapers/test_scraper_odds.py`

- Mock HTTP response from the-odds-api.com
- Test parsing of head-to-head and spread markets
- Test matchId mapping from API team names to our slug format
- Test implied probability calculation

### 2. [CODE] Create `scrapers/odds/scraper.py`

- `fetch_odds(season, round_number)` — calls the-odds-api.com
- `parse_odds(raw, round_matches)` — maps API response to our matchId format
- Calculates implied probabilities (normalised to remove overround)
- Averages across bookmakers for a consensus line

### 3. [CODE] Create `scrapers/odds/lambda_handler.py`

- Reads API key from Secrets Manager
- Fetches and parses odds
- Writes to `odds` DynamoDB table
- Handles API errors gracefully (odds are non-critical)

### 4. [TEST] Write `tests/scoring/test_odds_accuracy.py`

- Test that market accuracy is scored identically to prediction accuracy
- Test outlier detection logic

### 5. [CODE] Create `scoring/odds_accuracy.py`

- `score_market(match_id, odds_table, results_table)` — same metrics as `scorer.py`: correct pick, margin error, within 6/12 pts, Brier component
- `find_outliers(match_id, odds_table, predictions_table)` — returns matches where prediction and market disagree on winner or margin differs by >6pts

### 6. [CODE] Update `scoring/metrics.py`

- Add market accuracy aggregation alongside prediction accuracy
- New metrics: `market_pick_rate`, `market_avg_margin_error`, `market_brier`

### 7. [CODE] Update `api/predictions.py`

- Join odds onto prediction response: `pred["odds"] = { market_favourite, market_margin, home_odds, away_odds }`
- Add `is_outlier` flag when prediction disagrees with market

### 8. [CODE] Update `api/accuracy.py`

- Add market accuracy to the accuracy endpoint response
- Side-by-side comparison: AI vs market

### 9. [CODE] CDK updates (`infra/stack.py`)

- New `odds` DynamoDB table
- New `odds-scraper` Lambda
- New Secrets Manager reference for odds API key
- EventBridge: run odds scraper Tuesday 17:00 AEST + Friday 16:00 AEST (capture opening + closing odds)
- IAM grants: odds scraper reads secrets, writes odds table; scoring reads odds table; API reads odds table

### 10. [CODE] Frontend: outlier badge + market comparison

- Show odds alongside prediction on MatchCard
- Highlight outlier matches with a badge: "Disagrees with market"
- Accuracy dashboard: add market accuracy row for comparison

### 11. Update CLAUDE.md

- Add `odds` table to DynamoDB tables list
- Add odds scraper to package structure
- Add constraint about odds not being agent input
- Add EventBridge schedule for odds scraper

## Outlier Detection Logic

A match is an "outlier" when:
1. **Winner disagrees:** Our predicted winner differs from the market favourite, OR
2. **Margin diverges:** Our predicted margin differs from the market spread by >6 points

Outliers are the most interesting matches — they're where our model sees something the market doesn't (or vice versa).

## Accuracy Tracking

Market accuracy uses identical metrics to prediction accuracy:
- **Correct pick rate:** Did the market favourite win?
- **Margin error:** |market spread - actual margin|
- **Brier score:** Using implied probability as the confidence proxy
- **Calibration:** Do 70% implied probability teams win 70% of the time?

This enables direct comparison: "Our model picked 68% correctly this season vs the market's 72%."

## Cost

- the-odds-api.com free tier: 500 requests/month (we use ~64/month)
- DynamoDB: negligible (8 writes/week)
- Lambda: negligible

## Risks

- **API availability:** the-odds-api.com could go down or change their API. Odds are non-critical — the system works fine without them.
- **Team name mapping:** API uses full team names ("Penrith Panthers"), we use slugs ("panthers"). Need a mapping dict.
- **Overround removal:** Raw bookmaker odds sum to >100%. Need to normalise to get true implied probabilities.

## Definition of Done

- [ ] Odds scraped and stored for each match
- [ ] Market accuracy tracked with same metrics as predictions
- [ ] Outlier matches flagged in API response
- [ ] Frontend shows odds + outlier badge
- [ ] Accuracy dashboard shows AI vs market comparison
- [ ] CLAUDE.md updated with odds constraint and new resources
- [ ] Odds are NOT used as agent input (verified by code review)
