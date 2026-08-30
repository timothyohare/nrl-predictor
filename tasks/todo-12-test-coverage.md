# TODO — Plan 12 test-coverage hardening

Living checklist. See `tasks/plan-12-test-coverage.md` for detail and
`docs/plans/12-test-coverage-hardening.md` for rationale.

Baseline coverage (2026-08-30): **88%** v1 total.
Achieved (phases 1–7 integrated, 2026-08-30): **95.75%** line+branch, **758** tests.

## Status — all 8 phases implemented, PRs open

| Phase | PR | Branch | Result |
|---|---|---|---|
| Planning docs | #22 | `test/coverage-plan` | plan + this checklist |
| 1 — API layer | #24 | `test/phase-1-api` | `v1/api` 56% → **100%** |
| 2 — Tournament scoring | #25 | `test/phase-2-tournament-scoring` | `v1/tournament` 78% → **97%**; `variant_scorer.py` → 100% |
| 3 — Scoring + market | #27 | `test/phase-3-scoring` | `scoring/` 83% → **99%**; `metrics.py` + `lambda_handler.py` → 100% |
| 4 — Scrapers | #26 | `test/phase-4-scrapers` | `scrapers/` 90% → **96%**; 4 target files → 100%; odds 401 regression lock |
| 5 — Agent graph | #28 | `test/phase-5-agent-graph` | `v1/agent/graph.py` 73% → **100%** |
| 6 — Write-path boot-and-verify | #23 | `test/phase-6-write-path` | new `write_path.feature` (5 scenarios); `gate-verify` 16 BDD + acceptance green |
| 7 — Frontend infra | #29 | `test/phase-7-frontend` | Vitest + RTL; `lib` **100%**, components **96.5%**; `npm run build` green |
| 8 — Enforce | #30 | `test/phase-8-enforce` | `--cov-fail-under=93`; wired into `gate-ci`. **Merge last.** |

### Merge order
PRs #24–#29 in any order, then **#30 last** (`--cov-fail-under=93` fails on bare `main`).
#22 (planning docs) any time. #23 is independent (needs Docker for its gate).

### Production changes made during implementation (all minimal, noted in PRs)
- Phase 7: `splitMatchId` moved `components/MatchCard.tsx` → `lib/api.ts` (exported, behaviour unchanged) so it's unit-testable.
- No other source changes — phases 1–6 are test-only. No production bugs found.

## Follow-ups (not blocking — fold into the Phase 8 ratchet)
- [ ] Cover the remaining sub-90 files, then raise `--cov-fail-under`:
      `v1/agent/lambda_handler.py` 85%, `v1/agent/tools/web_search.py` 78%,
      `v1/retrospective/lambda_handler.py` 86%, `v1/retrospective/retrospective.py` 88%,
      `v1/orchestrator/lambda_handler.py` 87% (live-scrape paths),
      `scrapers/articles/body.py` 76%, `scrapers/nrl/team_sheet.py` 84%.
- [ ] `scrapers/nrl/backfill.py::backfill_season` — `records_skipped` counter is
      initialised but never incremented (cosmetic; completion log always says
      "0 skipped").
- [x] Re-check the `coverage_check` → `nrl-predictor-missing-predictions` alarm
      wiring gap from `CLAUDE.md` — root-caused (alarm `period=1h` + `NOT_BREACHING`
      vs. a once-a-day pulse metric) and fixed in PR #32 (`period` → 24h,
      `IGNORE` missing data, `put_metric_data` wrapped in try/except).
      `cdk deploy` confirmed live 2026-08-30.
- [ ] Phase 7 optional Playwright SSR smoke (`/`, `/predictions/[round]`,
      `/accuracy`, `/tournament`) — deferred; component tests judged sufficient.

## Rollup
- [x] All 8 phases implemented and pushed
- [x] All phase PRs merged (#22–#30, 2026-08-30)
- [x] Post-merge: `--cov-fail-under` raised 85 → 93 (main at 95.75%)
- [x] `docs/plans/12-*.md` status → done
- [ ] Continue the ratchet toward 96 as the sub-90 files above get covered
