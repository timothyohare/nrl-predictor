# TODO — monorepo migration

Ordered, dependency-aware. Each task done = its slice imports + tests + `cdk synth`
clean. Check the phase checkpoint before starting the next phase. See `tasks/plan.md`.

## Phase 0 — Baseline (no code changes)
- [x] T0.1 Capture `cdk synth` baselines for both stacks → `tasks/baseline/{v1,v2}.template.json` + `logical-ids.txt` (v1=114, v2=25 resources)
- [x] T0.2 Record both test suites green → `tasks/baseline/tests.md` (v1=288, v2=100)
- [x] **C0** baselines exist + green ✓ 2026-06-28

## Phase 1 — Subtree-merge v2 (history preserved)
- [x] T1.1 `git subtree add --prefix=v2` on branch `monorepo-merge`; v2 history reachable (fefba3c ancestor; 79=65+12+2 commits); v1 root untouched
- [x] **C1** root=v1, `v2/`=full v2; v1 suite green (288) ✓ 2026-06-28
      NOTE: `git log --follow v2/...` is empty by design — subtree grafts old root paths; history is reachable via commit ancestry (`git log fefba3c`).

## Phase 2 — Relocate v1 under `v1/` (absolute imports)
- [x] T2.1 v1 `api` → `v1/api` + imports + stack ApiLambda handler + tests; asset excludes v2/tasks/SPEC; api tests 12, full v1 288, logical IDs IDENTICAL, handler→`v1.api.router` ✓ 2026-06-28
- [x] T2.2 v1 `agent`,`orchestrator` → `v1/*` + imports (30 files) + AgentLambda/OrchestratorLambda handlers + tests; agent+orch 111, full v1 288, logical IDs IDENTICAL ✓ 2026-06-28
- [x] T2.3 v1 `tournament`,`retrospective` → `v1/*` + imports + 4 CDK handlers + tests (option b: frontend/scripts/docs/plans stay at root); tournament+retro 22, full v1 288, logical IDs IDENTICAL, ruff+mypy(v1+shared) clean ✓ 2026-06-28
- [x] **C2** root=shared+`v1/`+`v2/`; all v1 Python pkgs (api,agent,orchestrator,tournament,retrospective) under v1/; v1 green (288); template diff = Code/Handler-only ✓ 2026-06-28
      NOTE: full-repo gate-ci (mypy/ruff over `.`) deferred to C5 — v2/ still has bare `from agent…` imports until Phase 4; lint/type validated scoped to v1+shared.

## ⚠️ RESEQUENCED 2026-06-28 (see plan.md "Sequencing correction")
# Phase 4 (v2 rewire + single config) now runs BEFORE Phase 3 (drift deletion).
# Reason: v2/pyproject.toml makes v2/ a separate pytest rootdir; v2's bare
# `from scrapers/common/scoring` shadow root until v2 runs under one config.
# Deleting a shared dup can't be PROVEN until v2 is on the monorepo path.
# Drift *decisions* recorded as we go; ladder already decided (unify, root canon).

## Phase 4 (now first) — Rewire v2 onto v2.* + single config
- [x] T4.0 v2/__init__.py; single root pyproject (packages common*/scrapers*/scoring*/v1*/v2*; testpaths tests+v2/tests; --import-mode=importlib); removed v2/pyproject.toml; merged deps ✓
- [x] T4.1 v2 version imports → v2.* (25 files); shared stay bare→root; ruff merged (fixed 90+5); mypy excludes v2 (never typed pre-merge, follow-up); full suite 388 ✓
- [x] T4.2 v2 stack → v2.* handlers + asset REPO_ROOT=../.. bundles root-shared+v2/, excludes v1/; logical IDs IDENTICAL; asset verified (no v1 leak) ✓
- [x] **C4** v2 runs under unified config on v2.*; both suites 388 from one rootdir; v2 template diff = Code/Handler-only ✓ 2026-06-28
      FOLLOW-UPS: (1) type-check v2 (44 pre-existing mypy errors, currently excluded); (2) dead v2/api/tournament.py endpoint (no v2 tournament backend).

## Phase 3 (now after Phase 4) — Reconcile shared drift (delete dupes)
- [ ] T3.1 `scrapers/nrl/ladder.py` — DECISION: **unify, root canonical** (only diff UTC vs timezone.utc; parse_ladder identical). Delete v2 dup + prove both suites.
- [ ] T3.2 `scrapers/nrl/{draw,results,team_sheet,backfill}.py`
- [ ] T3.3 `scrapers/odds/{scraper,lambda_handler}.py`
- [ ] T3.4 `scrapers/articles/rss.py`, `scrapers/shared/http_client.py`
- [ ] T3.5 `scoring/{lambda_handler,metrics}.py`
- [ ] T3.final delete reconciled `v2/{common,scrapers,scoring}` dupes; v2 → root shared
- [ ] **C3** one copy per shared module (minus documented splits); both green

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
