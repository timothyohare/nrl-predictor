# SPEC — nrl-predictor monorepo (merge v1 + v2)

> Spec-driven development artifact. Status: **DRAFT — awaiting approval before /plan.**
> Lives in the repo that becomes the monorepo (`nrl-predictor`). Companion to the
> forthcoming `PLAN.md`.

## 1. Objective

Merge the two separate repos — `nrl-predictor` (v1, live single-loop predictor) and
`nrl-predictor2` (v2, LangGraph multi-agent rebuild) — into **one monorepo** so the
genuinely-shared code (`common/`, `scrapers/`, `scoring/`) has a **single source of
truth**, while **v1 and v2 continue to coexist and deploy independently** (they run
side by side long-term, not a migration to one).

**Why now:** the shared code is currently *copy-duplicated by hand* across two repos
with no submodule/package link. It has already silently drifted — `scrapers/` differs
in 9 source files and `scoring/` in 2 between the repos. That drift is exactly what
caused the 2026-06-28 ladder-scraper feed-change outage: the fix landed in one repo's
copy and the other's `cdk deploy` was a no-op. One source of truth makes a feed-shape
fix land once and cover both.

**Target users:** the maintainer (single developer) and the two deployed Lambda
fleets. No end-user-facing change; the live frontend and both prediction pipelines
must behave identically before and after.

**Decisions locked (2026-06-28):**
- Monorepo home = **the existing `nrl-predictor` GitHub repo** (65 commits, the live
  system). v2's 12 commits are merged in with history preserved; `nrl-predictor2`'s
  standalone repo is retired.
- Layout = **shared dirs at root + `v1/` and `v2/` version subtrees.**
- Drift reconciliation = **per-file, with the merged test suite as proof.**

## 2. Success criteria / acceptance

A1. **One copy of each shared module.** `common/`, `scrapers/`, `scoring/` exist once
    at the repo root; no `v1/`- or `v2/`-local duplicate of a shared file remains.
A2. **Version code is isolated and non-colliding.** v1's and v2's `agent/`, `api/`,
    `orchestrator/` (+ v1-only `frontend/`, `tournament/`; v2-only `tools/`,
    `retrospective/`) live under `v1/` and `v2/` and no longer collide by package name.
A3. **Both test suites pass from the one repo.** v1's pytest (currently green) and v2's
    pytest (currently 100 green) both run and pass via the merged harness — including
    the ladder regression tests already added in both repos.
A4. **Both CDK stacks still synth and deploy independently.** `NrlPredictorStack` (v1)
    and the v2 stack each `cdk synth` cleanly and target the same live AWS resources
    (table names, function names, EventBridge rules) they do today — no resource
    rename, no recreate. Verified by `cdk diff` showing **no infrastructure changes**.
A5. **Git history preserved.** `git log --follow` resolves history for files brought
    in from v2 (subtree merge, not a flat copy).
A6. **Drift is resolved, not frozen.** Each of the 11 drifted shared files is either
    (a) unified to one reconciled copy proven by tests, or (b) explicitly declared
    version-specific (moved under `v1/`/`v2/`) with a one-line rationale in PLAN.md.
A7. **Harness green end-to-end.** `gate-ci --full` (lint + typecheck + build) and
    `gate-verify` (boot + acceptance) pass for the merged repo.

**Non-goals:** no behavior change to either pipeline; no AWS resource renames; no
retirement of v1; no new sharing mechanism beyond the monorepo (no published package);
no frontend feature work.

## 3. Project structure (target)

```
nrl-predictor/                  # the monorepo (was v1)
  common/                       # SHARED — single source of truth (already identical)
  scrapers/                     # SHARED — reconcile 9 drifted files, then one copy
  scoring/                      # SHARED — reconcile 2 drifted files, then one copy
  v1/
    agent/  api/  orchestrator/  frontend/  tournament/  scripts/ ...
  v2/
    agent/  api/  orchestrator/  tools/  retrospective/  scripts/ ...
  infra/
    app.py                      # instantiates BOTH stacks
    v1_stack.py                 # = today's stack.py (live resources, imports v1.*)
    v2_stack.py                 # = v2's stack.py (agent_traces + v2 lambdas, imports v2.*)
  tests/                        # shared-module tests at root; v1/ and v2/ tests under their trees
  pyproject.toml                # one project; packages = common*, scrapers*, scoring*, v1*, v2*
  SPEC.md  PLAN.md
  .claude/harness.json          # merged bindings (see §5)
```

Open structural question to settle in /plan, not here: whether version-specific code
keeps `from agent...` imports (resolved per-Lambda by bundling only that version tree +
shared root onto the path) or is rewritten to `from v1.agent...`. Recommendation:
**rewrite to `v1.` / `v2.` absolute imports** so a single `pip install -e .` and a
single pytest run resolve unambiguously; Lambda assets bundle root-shared + the version
package. This is the largest mechanical task and PLAN.md will sequence it.

## 4. Commands

```bash
# Install once (editable, dev + viz extras)
pip install -e ".[dev]" --break-system-packages

# Tests — whole monorepo
python3 -m pytest                       # all
python3 -m pytest v2/ tests/            # v2 + shared
python3 -m pytest v1/ tests/            # v1 + shared

# Quality gates (the harness is the proof, per ~/.claude/CLAUDE.md)
node ~/.claude/bin/gate-ci.mjs --full   # lint + typecheck + build
node ~/.claude/bin/gate-verify.mjs      # boot + acceptance

# Deploy (independent per version, from infra/)
cd infra
AWS_DEFAULT_REGION=ap-southeast-2 cdk deploy NrlPredictorStack --require-approval never   # v1
AWS_DEFAULT_REGION=ap-southeast-2 cdk deploy NrlPredictorV2Stack --require-approval never # v2
cdk diff   # MUST show no infra changes during the migration
```

## 5. Testing & verification strategy

- **Reconciliation is test-gated.** For each drifted shared file: write/confirm a test
  that pins the correct behavior (prefer a fixture from the real captured feed, as the
  ladder fix did), then unify. If v1 and v2 need different behavior, the file is *not*
  shared — it moves under the version tree (records A6 rationale).
- **No-infra-change is the safety net for deploys.** `cdk diff` must be empty for both
  stacks at every checkpoint; a non-empty diff means an import/asset path moved a logical
  ID and risks resource replacement — stop and fix before deploying.
- **Both suites must stay green** throughout; the merge proceeds incrementally
  (shared dirs first, then v1 tree, then v2 tree) so a break is localized.
- **Harness:** merge the two `harness.json`. Keep v1's richer bindings (lint+frontend,
  typecheck, mockAws=dynamodb-local, boot/ready/acceptance, perf routes). Lint/test must
  cover `v1*`, `v2*`, and shared roots.

## 6. Boundaries

**Always:**
- Keep both pipelines behavior-identical; prove with both test suites + `cdk diff`.
- Preserve git history (subtree merge for v2).
- Slug team identity at boundaries; round-aware joins (inherited invariants).
- Run the harness gate and paste output before claiming a step done.

**Ask first:**
- Anything that changes a live AWS resource (table/function/rule name, IAM, schedule).
- `git push` / force-push / rewriting published history.
- Retiring or archiving the `nrl-predictor2` GitHub remote.
- Any change that makes `cdk diff` non-empty.

**Never:**
- Pass betting odds to any agent node (inherited v2 invariant).
- Recreate or rename the shared DynamoDB tables.
- Resolve drift by silently picking one copy without a test proving the choice.
- Hit the real Anthropic API in tests.
