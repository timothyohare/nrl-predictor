# PLAN — nrl-predictor monorepo migration

> Implements the approved `SPEC.md`. Read that first. Status: **DRAFT — awaiting
> approval before /build.** Companion task list: `tasks/todo.md`.

## The one invariant that protects production

Moving code under `v1/` and `v2/` and rewriting imports **will** change Lambda asset
hashes and handler strings — so `cdk diff` will **not** be literally empty. That is
expected and safe. The achievable, load-bearing invariant is:

> **No logical-ID changes, and no replacement of any stateful resource**
> (DynamoDB tables, S3 buckets, EventBridge rules, API Gateway). Lambda `Code` and
> `Handler` *in-place updates* are allowed.

Verified by diffing each stack's synthesized template against a **baseline captured in
Phase 0** (T0) and asserting: every resource keeps its logical ID, and no resource in
the diff is marked for replacement / `Type` change. v1 is the high-risk stack — it
*creates* the `predictions`/`teams`/`results`/`metrics`/… tables (v2 only imports them),
so a v1 logical-ID drift could threaten live data.

## Dependency graph (phases gate each other)

```
P0 baseline ──► P1 subtree-merge v2 ──► P2 move v1 under v1/ ──┐
                                                               ├─► P5 unify infra+harness ──► P6 verify+cutover
                          P3 reconcile shared drift ──► P4 rewire v2 ─┘
```
- P3 depends on P1 (needs v2's copies present at `v2/` to diff against root).
- P4 depends on P3 (v2 can't point at root-shared until drift is reconciled).
- P2 and P3 are independent of each other and can interleave; both must finish before P5.
- Every phase ends at a **checkpoint**: both affected test suites green + template diff
  clean. No phase starts until the prior checkpoint is green.

## Vertical slicing principle

Each task is one complete path — e.g. "move the v1 API: code + imports + its CDK
handler/asset + its tests, all green" — not "move all code, then fix all imports, then
fix all stacks." A task is done only when its slice imports, tests, and `cdk synth`
cleanly.

---

## Phase 0 — Baseline & safety net (no code changes)

**T0.1 Capture synth baselines.** `cdk synth` both stacks (v1 from its repo, v2 from
its repo, *pre-merge*) → save `tasks/baseline/v1.template.json`, `v2.template.json`,
and a `logical-ids.txt` (resource logical ID → type) for each.
*AC:* baseline files committed; `logical-ids.txt` lists every Lambda, table, rule, bucket.

**T0.2 Green baseline.** Run both test suites and record counts (v1 pytest; v2 pytest =
100). Save the merged-target Python version / deps notes.
*AC:* both suites green; counts recorded in `tasks/baseline/tests.md`.

**▶ Checkpoint C0:** baselines exist and are green. This is the reference for every
later "no logical-ID drift" check.

---

## Phase 1 — Merge v2 into v1 with history (no restructure)

**T1.1 Subtree-merge.** In the v1 repo, bring the entire v2 repo in under a `v2/`
prefix preserving history (`git subtree add --prefix v2 <v2-remote> main`, or
`git read-tree --prefix=v2/ -u` from a fetched ref). v1 code stays at root untouched.
*AC:* `git log --follow v2/scrapers/nrl/ladder.py` shows v2 commit history; root v1 tree
byte-identical to pre-merge; v1 pytest still green (root unchanged).
*Verify:* `git log -- v2/` non-empty; `git diff <pre> -- <root v1 files>` empty.

**▶ Checkpoint C1:** monorepo has root=v1, `v2/`=full v2 (incl its own duplicate
`common/scrapers/scoring`). Both trees independently importable. v1 suite green.

---

## Phase 2 — Relocate v1 version code under `v1/` (absolute imports)

One vertical task per v1 deployable; shared dirs (`common/scrapers/scoring`) stay at
root and are **not** moved.

**T2.1 v1 api.** `git mv api v1/api`; rewrite intra-v1 imports to `v1.api.*` /
`v1.<pkg>.*`; leave `from common…/scrapers…/scoring…` as-is (root). Update v1 stack's
ApiFn `handler=` to `v1.api.…` and asset excludes. Update v1 api tests.
*AC:* `pytest v1/... tests/` for api green; `cdk synth` v1 → ApiFn logical ID unchanged,
only Code/Handler differ vs C0 baseline.

**T2.2 v1 agent + orchestrator + scoring-handlers.** Same pattern for `agent/`,
`orchestrator/` (and any v1 Lambda handlers). Rewrite to `v1.*`; update each Function's
`handler=`; update tests.
*AC:* v1 pytest green; every v1 Function keeps its logical ID; no stateful resource in
the diff.

**T2.3 v1 leftovers.** Move `frontend/`, `tournament/`, `scripts/`, `docs/` etc. under
`v1/` (or keep `frontend/` at a path the harness build expects — decide in slice).
Update `harness.json` paths provisionally.
*AC:* `gate-ci` (lint+typecheck) green for v1 tree; frontend build still resolves.

**▶ Checkpoint C2:** root = shared dirs only + `v1/` + `v2/`. v1 fully under `v1/`,
absolute-imported, tests green, v1 template diff = Code/Handler-only.

---

## Phase 3 — Reconcile shared-dir drift (root vs `v2/`)

`common/` is already identical. Reconcile the **11 drifted files**: `scrapers/` (rss,
backfill, draw, ladder, results, team_sheet, odds/lambda_handler, odds/scraper,
shared/http_client) and `scoring/` (lambda_handler, metrics). One vertical task per file
or tight cluster.

**T3.x (per file/cluster)** Diff root (v1) vs `v2/` copy. Decide:
- **(a) Unify** — pick/merge the correct version, prove with the tests from *both*
  suites that exercise it (prefer a real-feed fixture, per the ladder fix). Then point
  v2 at the root copy and delete `v2/<file>`.
- **(b) Split** — if v1 and v2 legitimately need different behavior (e.g. v2's slug
  identity), the file is **not shared**: keep v2's under `v2/`, record a one-line
  rationale in this plan's "Drift decisions" table. (Expected for some scraper/scoring
  files touched by the v2 slug-identity work.)
*AC per task:* decision recorded; if unified, root copy passes both suites and no `v2/`
duplicate remains; if split, rationale logged.

**T3.final Delete reconciled duplicates.** Remove `v2/common`, and any unified
`v2/scrapers`,`v2/scoring` files; v2 imports resolve `common/scrapers/scoring` from root.
*AC:* no shared file exists in two places except those explicitly marked "split".

### Sequencing correction (2026-06-28, during T3.1)
Phase 3 (delete shared dupes) **depends on** Phase 4 + single-config: `v2/pyproject.toml`
makes `v2/` a separate pytest rootdir, so v2's bare `from scrapers/common/scoring`
shadow the root copies until v2 runs under one config on the monorepo path. A dup
deletion can't be *proven* until then. **Resolved by running Phase 4 (v2 rewire + single
root pyproject) before Phase 3.** Drift *decisions* are still recorded as encountered.

### Drift decisions — ALL 11 UNIFY ON ROOT, no splits (2026-06-28)
8 files functionally identical (comments/imports/whitespace only). 3 substantive — root
is a superset in every case; v2 had no fix root lacked, and v2's tests already passed
against root copies (388). Deleted `v2/{common,scrapers,scoring}` entirely.
| file | decision | rationale |
|---|---|---|
| ladder, results, backfill, odds/scraper, odds/lambda_handler, articles/rss, shared/http_client, scoring/metrics | **unify (root)** | functionally identical (only UTC-spelling / import-order / comments) |
| `scrapers/nrl/draw.py` | **unify (root)** | root superset: adds `slug_from_match_centre_url` back-compat alias; same output as v2's inline `match_id_from_url` |
| `scrapers/nrl/team_sheet.py` | **unify (root)** | root superset: defensive `json.loads(str(...))` cast + alias; equivalent behaviour |
| `scoring/lambda_handler.py` | **unify (root)** | root superset: returns informative `{"status":"OK"}` on success (v2 returned None); async invocation ignores return, tests unaffected |

**▶ Checkpoint C3:** one copy of each shared module at root (minus any documented
splits). Both suites green.

---

## Phase 4 — Rewire v2 onto shared root + version imports

**T4.1 v2 version imports.** Rewrite v2 version code (`v2/agent`, `v2/api`,
`v2/orchestrator`, `v2/tools`, `v2/retrospective`) to absolute `v2.*` for intra-v2 and
bare `common/scrapers/scoring` for shared (root).
*AC:* `pytest v2/ tests/` green (target: the 100 v2 tests + ladder tests).

**T4.2 v2 stack rewire.** Update v2 stack: each Function `handler=` `agent.…`→`v2.agent.…`
etc.; the `Code.from_asset` payload must bundle **root-shared + `v2/`** and exclude `v1/`;
keep `DepsLayer` bundling as-is.
*AC:* `cdk synth` v2 → AgentFn/OrchestratorFn/ApiFn keep logical IDs; AgentTraces table +
all imported tables unchanged; only Code/Handler differ vs C0 baseline.

**▶ Checkpoint C4:** v2 runs entirely on root-shared code; v2 template diff =
Code/Handler-only.

---

## Phase 5 — Unify infra, harness, packaging

**T5.1 One CDK app.** `infra/app.py` instantiates **both** stacks; rename
`stack.py`→`v1_stack.py`, add `v2_stack.py`; single `cdk.json` (merge context keys).
*AC:* `cdk ls` shows `NrlPredictorStack` and `NrlPredictorV2Stack`; both `cdk synth`.

**T5.2 One pyproject.** Merge to a single project; `packages.find` include =
`common*, scrapers*, scoring*, v1*, v2*`. Reconcile deps + extras (`dev`, `viz`).
*AC:* clean `pip install -e ".[dev]"`; `python -c "import v1.api, v2.agent, scrapers, common"`.

**T5.3 One harness.** Merge `harness.json` (keep v1's richer bindings); lint/test globs
cover `v1*`,`v2*`,shared; fix boot/acceptance/perf paths for new frontend/script
locations. Update root `CLAUDE.md` to describe the monorepo layout.
*AC:* `gate-ci --full` (lint+typecheck+build) green; `gate-verify` green.

**▶ Checkpoint C5:** single repo builds, installs, lints, types, tests, boots & verifies
from one harness.

---

## Phase 6 — Final verification & gated cutover

**T6.1 Template no-drift proof.** Diff both synthesized templates vs `tasks/baseline/`:
assert no logical-ID added/removed, no stateful resource replaced/typed-changed; the
only deltas are Lambda Code/Handler. Write `tasks/baseline/diff-report.md`.
*AC:* report shows zero logical-ID/stateful changes.

**T6.2 Full gate.** `gate-ci --full` + `gate-verify` green; both pytest suites green.
*AC:* all gates green, output pasted into the build log.

**T6.3 (ASK-FIRST, gated) Deploy + cutover.** With explicit approval: `cdk diff` review,
then deploy v1 and v2 from the monorepo; confirm live functions updated (LastModified) and
a smoke pred/scrape works; then retire the `nrl-predictor2` GitHub remote and push.
*AC:* both stacks deployed from monorepo; live smoke passes; **no `git push` or remote
retirement without explicit go-ahead.**

**▶ Checkpoint C6:** monorepo is the single source of truth; both fleets deploy from it.

---

## Risks & mitigations
- **Live-table replacement (v1 owns tables).** → T0 baseline + T6.1 logical-ID assertion;
  never touch table construct IDs.
- **Hidden intentional drift in scrapers/scoring (v2 slug work).** → P3 per-file decision
  with split-allowed; tests prove unify is safe.
- **Import-rewrite breakage at scale.** → vertical per-package slices, suite green per task.
- **Frontend build path moves.** → T2.3/T5.3 fix harness `build`/`boot` paths explicitly.
- **Subtree history mistakes.** → T1.1 verifies `git log --follow` before proceeding.
