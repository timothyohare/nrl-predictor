# NRL Predictor security assessment

**Date:** 27 September 2026
**Scope:** Public prediction/leaderboard handlers, frontend security headers, dependency lockfile. Testing used mocked DynamoDB for fuzzing; production probes were a health GET and one malformed season GET. No writes, load tests or private AWS data were used.

## Findings

### NRL-01 — Malformed tournament season returned HTTP 500 (Medium)

`tournament.py` converted the caller's `season` directly to an integer. Nonnumeric input escaped as an exception. One production GET returned 500 with a generic body.

**Implemented:** Conversion failures and seasons outside 1998 through next year now return 400 before storage access. The new seeded test corpus exercises malformed and oversized strings, plus range errors.

### NRL-02 — Excessive round values reached storage (Low/Medium)

`predictions.py` parsed arbitrarily large round integers before scanning. A 100-digit value reached the mocked database path.

**Implemented:** Rejects round numbers outside 0–99 before any table access. This preserves the existing 99→404 behavior while bounding the input. Existing handlers still use paginated full-table scans; replacing them with indexed queries remains a follow-up cost-control item.

### NRL-03 — Vulnerable Next.js version in frontend lockfile (Critical advisory match; exposure conditional)

The assessment lockfile matched critical Next.js advisories, including AVIF image-optimization RCE before 16.3.3. Matching an advisory does not by itself prove production reachability or compromise.

**Implemented:** Updated the frontend dependency and lockfile to exact Next.js 16.3.3 with install scripts disabled. This is the advisory's patched release. Re-run audit and build; verify deployment runtime/version and AVIF configuration after release.

### NRL-04 — Missing browser response headers (Low)

The public page lacked HSTS, `nosniff`, and framing controls.

**Implemented:** Next.js now returns HSTS, content-type, frame, referrer, permissions and a framing/content policy on routes.

**Retest:** The production page is unchanged until deployment. Run the captured header gate on the site after deployment and confirm the headers do not conflict with Next's asset requirements.

## Verification

Local security tests cover 305 seeded malformed round inputs, invalid tournament seasons and no-storage-on-invalid assertions. The final root `ci.mjs --force --full` gate passes (686 Python tests, 99 frontend tests, and production build); the focused security gate also passes (7 tests, coverage above 93%). `fuzz.mjs --examples 25` passes 49/49 generated cases with seed 42. It covers only two OpenAPI operations and warns that `/predictions/{round}` lacks valid fixtures and schema constraints do not match API validation. `npm audit` reports zero known advisories after updating Next.js and affected transitive packages. Production retest remains a release requirement; the live site was not changed.
