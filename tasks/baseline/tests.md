# Test baselines (Phase 0 / C0)

Captured 2026-06-28, pre-merge. These are the green counts the merged monorepo must
match or exceed (no test lost in the move).

| repo | command | result |
|---|---|---|
| v1 (nrl-predictor) | `AWS_DEFAULT_REGION=ap-southeast-2 AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test .venv/bin/python -m pytest -q` | **288 passed** in ~21s |
| v2 (nrl-predictor2) | `python3 -m pytest -q` | **100 passed** in ~3s |

Both moto-mocked; no live AWS touched.

## Synth baselines (T0.1)
| stack | template | resources |
|---|---|---|
| NrlPredictorStack (v1) | `v1.template.json` | 114 (13 DynamoDB tables, 1 S3 bucket, 9 Events rules, 15 Lambdas, + IAM/perms) |
| NrlPredictorV2Stack (v2) | `v2.template.json` | 25 (3 Lambdas, AgentTraces table, HTTP API, DepsLayer, + IAM/rules/perms) |

Logical-ID → Type maps: `v1.logical-ids.txt`, `v2.logical-ids.txt`. These must remain
invariant through the migration (only Lambda `Code`/`Handler` may change). v1 is the
high-risk stack — it **creates** the stateful tables; v2 only imports them.
