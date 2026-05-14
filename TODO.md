# Human TODOs

Tasks that require manual action outside of code (AWS console, credentials, infra wiring, etc.).

---

## ~~AWS Secrets Manager~~ DONE

Both `nrl-predictor/anthropic-api-key` and `nrl-predictor/tavily-api-key` populated 2026-05-13.

---

## ~~CDK~~ DONE — deployed 2026-05-13

Stack outputs:
- API endpoint: `https://2jjj64x7ih.execute-api.ap-southeast-2.amazonaws.com`
- Agent Lambda ARN: `arn:aws:lambda:ap-southeast-2:810429055117:function:nrl-predictor-agent`
- Raw S3 bucket: `nrl-predictor-raw-scrapes`

---

## ~~Amplify build~~ DONE — deployed 2026-05-13

App ID: `dmazwh64vi4cy`  
Amplify URL: `https://main.dmazwh64vi4cy.amplifyapp.com/`

Build works. Key lessons learned:
- `amplify.yml` must use `appRoot: frontend` format (not `cd frontend &&`) to avoid rvm `cd` hook bug in Amplify's build environment.
- Env vars set: `API_GATEWAY_URL` and `NEXT_PUBLIC_API_BASE_URL` both pointing to the API Gateway endpoint above.

---

## Amplify SSR fix — job 5 deploying (check status tomorrow)

Root cause of 404: Amplify app was set to `platform: WEB` (static S3 hosting) instead of
`platform: WEB_COMPUTE` (SSR). Fixed via CLI on 2026-05-13:

```bash
aws amplify update-app --app-id dmazwh64vi4cy --platform WEB_COMPUTE --region ap-southeast-2
```

A redeploy was triggered (job 5). Check its status:

```bash
aws amplify get-job --app-id dmazwh64vi4cy --branch-name main --job-id 5 \
  --region ap-southeast-2 --query "job.summary.status"
```

Once job 5 is SUCCEED, verify both URLs respond with HTML (not S3 404):

```bash
curl -si https://main.dmazwh64vi4cy.amplifyapp.com/ | head -5
curl -si https://nrl-predictor.ohare.id.au/ | head -5
```

Expected: `server: CloudFront` (not `server: AmazonS3`) and HTTP 200.

---

## Historical backfill — run once

Once confirmed the site and API are working end-to-end, seed historical results:

```bash
AWS_DEFAULT_REGION=ap-southeast-2 \
  .venv/bin/python3 -m scrapers.nrl.backfill --seasons 2025 2026
```

Expected: ~430 records (27 rounds × 8 matches × 2 seasons).

---

## Anthropic Console — spend limit

- Settings → Billing → Usage limits → set monthly hard cap to **$20 USD**
- Set email alert at **$10 USD** (50%)

---

## Manual integration tests (run before launch)

- Invoke draw scraper Lambda manually and verify records appear in `teams` DynamoDB table
- Invoke agent Lambda for one match and verify prediction appears in `predictions` table
- Hit `curl https://2jjj64x7ih.execute-api.ap-southeast-2.amazonaws.com/predictions/12` and confirm JSON response
- Verify `https://nrl-predictor.ohare.id.au/predictions/12` renders predictions (not empty shell)
- Verify `https://nrl-predictor.ohare.id.au/robots.txt` is accessible
- Submit sitemap to Google Search Console once custom domain resolves
