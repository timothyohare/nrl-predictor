# Human TODOs

Tasks that require manual action outside of code (AWS console, credentials, infra wiring, etc.).

---

## ~~AWS Secrets Manager~~ DONE

Both `nrl-predictor/anthropic-api-key` and `nrl-predictor/tavily-api-key` populated 2026-05-13.

---

## Historical backfill — run once after deploying the results scraper Lambda

Once the results scraper Lambda is deployed and the `results` DynamoDB table is live:

```bash
AWS_DEFAULT_REGION=ap-southeast-2 \
  .venv/bin/python3 -m scrapers.nrl.backfill --seasons 2025 2026
```

Verify record count in DynamoDB console (~27 rounds × 8 matches × 2 seasons ≈ 430 records).

---

## ~~CDK~~ DONE — deployed 2026-05-13

Stack outputs:
- API endpoint: `https://2jjj64x7ih.execute-api.ap-southeast-2.amazonaws.com`
- Agent Lambda ARN: `arn:aws:lambda:ap-southeast-2:810429055117:function:nrl-predictor-agent`
- Raw S3 bucket: `nrl-predictor-raw-scrapes`

---

## Amplify — set up front end hosting

The Next.js frontend is in `frontend/`. It uses ISR (`revalidate=300`) for predictions,
SSR for accuracy, and SSG for how-it-works.

- Connect GitHub repo to AWS Amplify; configure build: `cd frontend && npm run build`
- Add custom domain `nrl-predictor.ohare.id.au` in Amplify console
- Add CNAME `nrl-predictor` → Amplify CloudFront domain in Route 53 (existing `ohare.id.au` hosted zone)
- Set Amplify env vars:
  - `API_GATEWAY_URL=https://2jjj64x7ih.execute-api.ap-southeast-2.amazonaws.com`
  - `NEXT_PUBLIC_API_BASE_URL=https://2jjj64x7ih.execute-api.ap-southeast-2.amazonaws.com`
- Do NOT add `output: 'export'` to `next.config.js` — breaks SSR/ISR

---

## Anthropic Console — spend limit

- Settings → Billing → Usage limits → set monthly hard cap to **$20 USD**
- Set email alert at **$10 USD** (50%)

---

## Frontend — install dependencies and verify build

```bash
cd frontend
npm install
npm run build   # should pass with no type errors
```

---

## Node version

Node is upgraded to latest LTS (done). Verify CDK no longer warns on run.

---

## Manual integration tests (run before launch)

- Run agent end-to-end (no mocks) against live DynamoDB/S3 for one historical round with known outcomes
- Simulate peak load: invoke 8 agent Lambdas in parallel, verify no throttling
- Verify `curl https://nrl-predictor.ohare.id.au/predictions/12` returns prediction HTML (not loading shell)
- Verify `robots.txt` accessible at the public URL
- Submit sitemap to Google Search Console
