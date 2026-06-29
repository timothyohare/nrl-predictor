# C6 / T6.1 — Template no-drift proof (monorepo vs pre-merge baseline)

Both stacks synthesized from the unified `infra/app.py` and compared to the Phase-0
baselines (`v1.template.json`, `v2.template.json`) captured before any code moved.

## Invariant checked
> No logical-ID added/removed/retyped; no replacement of any stateful resource.
> Only Lambda `Code`/`Handler` (and benign IAM consolidation) may change.

## Results

| stack | logical-ID diff | property drift (asset-hash + Handler masked) |
|---|---|---|
| **NrlPredictorStack (v1)** | **IDENTICAL** (114 resources) | **none** |
| **NrlPredictorV2Stack (v2)** | **IDENTICAL** (25 resources) | IAM policies only — see below |

- **Logical IDs:** every resource keeps its logical ID in both stacks → no
  CloudFormation replacement; the live DynamoDB tables, S3 bucket, EventBridge rules,
  API Gateway, and Lambda *resources* are untouched.
- **Expected changes (safe):** Lambda `Code` (asset hash, since code moved under
  `v1/`/`v2/`) and `Handler` (`agent.*`→`v1.agent.*` / `v2.agent.*`). These are
  in-place updates on next deploy, not replacements.
- **v2 IAM consolidation (benign):** the merged `cdk.json` applies
  `@aws-cdk/aws-iam:minimizePolicies` (a v1 flag) to v2, consolidating v2's policy
  statements **34 → 10**. Verified the granted **action set is unchanged** — same
  effective permissions, fewer statements. On next v2 deploy CloudFormation updates
  the IAM policy documents once; no permission gained or lost.

## Verification commands (reproducible)
```bash
cd infra && cdk synth NrlPredictorStack --json   # vs tasks/baseline/v1.template.json
              cdk synth NrlPredictorV2Stack --json # vs tasks/baseline/v2.template.json
# logical-ID lists compared with: jq '.Resources|to_entries[]|"\(.key)\t\(.value.Type)"'
```

## Gates (T6.2)
- `gate-ci --full`: **green** — ruff, mypy (v1+shared), 388 tests (288 v1 + 100 v2),
  frontend build.
- `gate-verify`: **green** — v1 API boots from the monorepo against dynamodb-local;
  all 14 acceptance checks pass.

## Conclusion
The monorepo is behavior-equivalent to the two pre-merge repos. Safe to deploy both
stacks; expect Lambda Code/Handler updates on both and a one-time IAM policy
consolidation on v2. **T6.3 (deploy + retire v2 remote) is gated on explicit approval.**
