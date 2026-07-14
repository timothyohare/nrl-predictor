# Lesson: two Lambdas were deployed pointing at handler modules that were never written

**Date diagnosed:** 2026-07-14 · **Broken since:** 2026-05-13 (first deploy, commit `ce93d38`)

## What happened

`nrl-predictor-weather-scraper` and `nrl-predictor-articles-scraper` failed **every
scheduled run for two months** with:

```
Runtime.ImportModuleError: Unable to import module 'scrapers.weather.lambda_handler':
No module named 'scrapers.weather.lambda_handler'
```

`infra/v1_stack.py` declared handlers `scrapers.weather.lambda_handler.lambda_handler`
and `scrapers.articles.lambda_handler.lambda_handler`, but only the library code
(`weather.py`, `venues.py`; `rss.py`, `body.py`, `haiku_extractor.py`) was ever written —
the handler modules did not exist at any point in git history. The CDK handler strings
were written by analogy with the odds scraper (which does have a `lambda_handler.py`)
and never wired to real code.

**Impact:** the `weather` and `injuries` DynamoDB tables held **zero items**. The agent's
`get_weather` and `get_injury_list` tools read those tables, so every prediction of the
season ran with no weather and no injury-news input — silently, because a tool returning
nothing doesn't fail the prediction.

## Why it went unnoticed for two months

1. **The alarms fired and self-recovered.** Each `Errors` alarm (`period=1800`, `Sum >= 1`,
   `treat_missing_data=notBreaching`) went ALARM on the scheduled run and back to OK ~90
   minutes later when the metric went missing. Nothing stayed red long enough to be seen
   on a dashboard, and the OK email arriving right after the ALARM email trains you to
   ignore both.
2. **Import errors produce no application logs.** The module fails before any code runs,
   so there were no log lines from our code to stumble over while debugging other things.
3. **Nothing validated "handler string → real module".** `cdk deploy` happily deploys a
   handler path that doesn't exist in the asset; Lambda only resolves it at invoke time.
4. **Tests covered the library, not the entry point.** `tests/scrapers/test_scraper_weather.py`
   etc. tested parsing thoroughly — but no test imported the module the infrastructure
   actually invokes.
5. **Downstream consumers degrade silently.** Agent tools returning empty results don't
   error, and prediction quality regressions are invisible without a data-presence check.
   (Same failure shape as the June team-sheet keying bug.)

## Rules going forward

- **Every `handler=` string in `infra/` must have a test that imports that exact module
  and asserts `lambda_handler` exists.** Cheapest possible guard; would have caught this
  on day one. (The new handler test files do this implicitly by importing the modules;
  a dedicated infra↔code audit test is the stronger form.)
- **A new Lambda isn't "done" at deploy — it's done when its first scheduled/manual
  invocation is verified in the logs and its output lands in the target table.**
  Boot-and-verify (`gate-verify`) covers the API read path; anything outside it needs a
  one-off invoke + table check before being declared shipped.
- **Alarm on absence, not just errors.** The plan for a round-coverage alert (predictions
  < draw matches) generalises: freshness/presence checks on `weather` and `injuries`
  would have surfaced this in week one even with alarms misconfigured.
- **Repeated fire-then-recover alarms are a signal, not noise.** An alarm that cycles on
  every scheduled run of the same function is a hard failure with a self-resetting
  metric, not flakiness — check the history (`describe-alarm-history`) instead of
  reading only the latest state.
