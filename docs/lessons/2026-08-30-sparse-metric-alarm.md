# Lesson: an alarm on a once-a-day "pulse" metric never fires with a 1-hour period

**Date diagnosed:** 2026-08-30 · **Broken since:** 2026-07-15 (commit `f9dd8a9`, the
commit that introduced both the metric and the alarm) · **Fixed:** PR #32

## What happened

`nrl-predictor-coverage-check` (`v1/orchestrator/coverage_check.py`) ran on every
schedule during the round-25 outage, correctly computed `missing = 8/8`, logged
`Round 25 under-predicted: 0/8 …`, and called `put_metric_data` for
`NrlPredictor/MissingPredictions = 8`. The `nrl-predictor-missing-predictions`
alarm **sat in OK the entire time**, state reason "no datapoints were received
over the period of 1 hour and 1 datapoint(s) treated as NonBreaching". No email
was ever sent. The round was invisible on the site for its whole duration with
no alert.

## Root cause

The emit side was fine — namespace, metric name, dimensions (none), region, and
the `cloudwatch:PutMetricData` IAM grant (`resources=["*"]`, condition
`cloudwatch:namespace = NrlPredictor` satisfied by the call) all matched the
alarm.

The bug was the **alarm definition** in `infra/v1_stack.py`. `PredictionCoverageAlarm`
was written by analogy with the stack's `*ErrorAlarm`s — `period=1h`,
`evaluation_periods=1`, `treat_missing_data=NOT_BREACHING`. That config is
correct for `fn.metric_errors()`, a **continuous** Lambda built-in metric that
emits a datapoint (even `0`) on every invocation.

`NrlPredictor/MissingPredictions` is not continuous. It's a **pulse**:
`coverage_check` publishes exactly one datapoint per run, and the run is
scheduled at most ~once a day (Tue / Thu / Fri×2 / Sat). Against a pulse:

1. **`period=1h` + custom-metric ingestion lag.** The Lambda publishes at
   ~07:30; a standard-resolution custom metric isn't reliably alarm-visible for
   5–15 min. CloudWatch evaluates the 07:00–08:00 window at ~08:00 — often
   before the point has propagated — sees an empty window, applies
   `NOT_BREACHING` → OK. It then evaluates 08:00–09:00, which is empty. **The
   one hour that contains the breaching datapoint is never re-evaluated with the
   data present.** That is the exact "no datapoints were received over the
   period" state reason.
2. **`NOT_BREACHING` erases the signal.** Even when timing lines up for one
   hour, the next empty hourly evaluation forces the state straight back to OK.
   Over a multi-day outage (same value `8` every run) there's no re-transition,
   so at best you get one fragile ~1h ALARM blip and one email — and in practice
   not even that.

This is the **second instance of the same anti-pattern**. See
`2026-07-14-missing-lambda-handlers.md` → "Why it went unnoticed", point 1: the
scraper `Errors` alarms (`period=1800`, `NOT_BREACHING`) fired then self-cleared
~90 min later when the metric went missing, so nothing stayed red long enough to
be seen.

## The fix

`PredictionCoverageAlarm`:

| | before | after |
|---|---|---|
| `period` | `1h` | **`24h`** — the daily pulse always lands inside the evaluated window |
| `treat_missing_data` | `NOT_BREACHING` | **`IGNORE`** — missing data holds the last state |
| `datapoints_to_alarm` | (default) | **`1`** — one breaching pulse is enough |

With `IGNORE`, once a bad datapoint trips the alarm it **stays ALARM** through
the empty periods until a later coverage run publishes `MissingPredictions = 0`
and clears it — a sticky alarm, one email, red until fixed. That is the correct
shape for "a round is under-predicted and stays that way until someone acts."

Also wrapped `put_metric_data` in `try/except` + `logger.exception` so a
CloudWatch failure can't abort the handler before it logs (the log line is the
source of truth).

`cdk deploy NrlPredictorStack` + `aws cloudwatch describe-alarms` confirmed
`Period: 86400`, `TreatMissingData: ignore`, `DatapointsToAlarm: 1`.

## Rules going forward

- **Match the alarm's `period` and missing-data treatment to the metric's
  cadence.** Continuous metric → short period + `NOT_BREACHING` is fine. Metric
  written N times a day by a cron → `period ≥` the largest gap between writes,
  and `treat_missing_data = IGNORE` (or `BREACHING`), never `NOT_BREACHING`
  (which makes the gaps overwrite the signal).
- **Don't copy the `*ErrorAlarm` config for a custom metric.** `fn.metric_errors()`
  is continuous; almost nothing we `put_metric_data` ourselves is.
- **A custom-metric alarm isn't "done" at deploy.** Verify it end-to-end:
  `set-alarm-state … ALARM` to confirm the SNS path delivers, and check
  `describe-alarm-history` after the next real pulse to confirm it transitioned.
- **Prefer sticky alarms for "condition persists until a human acts" signals.**
  `IGNORE` + a later healthy datapoint to clear beats a fire-then-self-recover
  blip that trains you to ignore the email.
