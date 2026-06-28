# TODO — monorepo migration

Ordered, dependency-aware. Each task done = its slice imports + tests + `cdk synth`
clean. Check the phase checkpoint before starting the next phase. See `tasks/plan.md`.

## Phase 0 — Baseline (no code changes)
- [x] T0.1 Capture `cdk synth` baselines for both stacks → `tasks/baseline/{v1,v2}.template.json` + `logical-ids.txt` (v1=114, v2=25 resources)
- [x] T0.2 Record both test suites green → `tasks/baseline/tests.md` (v1=288, v2=100)
- [x] **C0** baselines exist + green ✓ 2026-06-28

## Phase 1 — Subtree-merge v2 (history preserved)
- [ ] T1.1 `git subtree add --prefix v2` (or read-tree); verify `git log --follow v2/...`; v1 root untouched + green
- [ ] **C1** root=v1, `v2/`=full v2; v1 suite green

## Phase 2 — Relocate v1 under `v1/` (absolute imports)
- [ ] T2.1 v1 `api` → `v1/api` + imports + stack ApiFn handler/asset + tests
- [ ] T2.2 v1 `agent`,`orchestrator` (+ handlers) → `v1/*` + imports + stack handlers + tests
- [ ] T2.3 v1 `frontend`,`tournament`,`scripts`,`docs` → `v1/*`; provisional harness paths
- [ ] **C2** root=shared+`v1/`+`v2/`; v1 green; template diff = Code/Handler-only

## Phase 3 — Reconcile shared drift (root vs `v2/`)
- [ ] T3.1 `scrapers/nrl/ladder.py` (unify; real-feed fixture both suites)
- [ ] T3.2 `scrapers/nrl/{draw,results,team_sheet,backfill}.py`
- [ ] T3.3 `scrapers/odds/{scraper,lambda_handler}.py`
- [ ] T3.4 `scrapers/articles/rss.py`, `scrapers/shared/http_client.py`
- [ ] T3.5 `scoring/{lambda_handler,metrics}.py`
- [ ] T3.final delete reconciled `v2/{common,scrapers,scoring}` dupes; v2 → root shared
- [ ] **C3** one copy per shared module (minus documented splits); both green

## Phase 4 — Rewire v2 onto shared root
- [ ] T4.1 v2 version imports → `v2.*` + bare `common/scrapers/scoring`; `pytest v2/ tests/` green
- [ ] T4.2 v2 stack handlers `→ v2.*` + asset bundles root-shared+`v2/`, excludes `v1/`; logical IDs stable
- [ ] **C4** v2 on root-shared; template diff = Code/Handler-only

## Phase 5 — Unify infra + harness + packaging
- [ ] T5.1 `infra/app.py` both stacks; `v1_stack.py`/`v2_stack.py`; one `cdk.json`
- [ ] T5.2 one `pyproject.toml` (packages: common*,scrapers*,scoring*,v1*,v2*); install clean
- [ ] T5.3 merge `harness.json` (v1-rich, globs cover v1*/v2*/shared); update root `CLAUDE.md`
- [ ] **C5** `gate-ci --full` + `gate-verify` green

## Phase 6 — Verify + gated cutover
- [ ] T6.1 template no-drift proof vs baseline → `tasks/baseline/diff-report.md`
- [ ] T6.2 full gate (`gate-ci --full`, `gate-verify`, both pytest) green, output pasted
- [ ] T6.3 **ASK-FIRST** deploy both from monorepo + smoke + retire v2 remote (no push without go-ahead)
- [ ] **C6** monorepo is single source of truth
