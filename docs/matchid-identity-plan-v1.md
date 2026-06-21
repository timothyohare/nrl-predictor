# Match identity (v1) — canonical matchId for the live predictor

**Status:** proposal · **Repo:** `nrl-predictor` (v1, **serves the live site**)
**Master plan:** `nrl-predictor2/docs/matchid-identity-plan.md` (full rationale + options)

v1-specific cut. The headline: **v1's live path is already safe**, so this is mostly hardening +
coordinating the shared-table cleanup — not an emergency.

## Where v1 stands today

- `matchId` is intended to be the round-prefixed slug from the match-centre URL
  (`slug_from_match_centre_url()` in `scrapers/nrl/draw.py`, docstring: *"the canonical matchId used
  everywhere downstream"*). v1's results scraper derives it identically.
- **The live API is already round-aware**: `api/predictions.py` joins results by `matchId` *and*
  filters on `roundNumber`, and only the scoring write-back row carries `roundNumber`, so legacy
  raw rows are excluded (`api/predictions.py:57-69`). The public site is **not** showing bogus
  cross-round results (unlike the v2 inspector, which joins round-blind).
- The shared `results` table still contains legacy non-canonical rows — round-less
  (`dragons-v-knights`) and reversed-order (`knights-v-raiders` vs `raiders-v-knights`) — written by
  older/raw paths. They have no `roundNumber`, so the v1 API ignores them, but they are latent
  traps for any new joiner and make `scoring`'s by-matchId lookup fragile.

## Target

One helper as the single matchId definition; every v1 writer routes through it; every join is
round-aware (by `matchId` / `roundNumber`, never team-pair). Canonical form:
`round-<N>-<home-slug>-v-<away-slug>`, home/away in official draw order, team slugs from the
[team-identity plan](team-identity-plan-v1.md).

## v1 file inventory

**Producers → canonical matchId via the helper**
- `scrapers/nrl/draw.py` (`slug_from_match_centre_url` — promote to the shared SSOT), `results.py`,
  `team_sheet.py`, `backfill.py`, `scrapers/odds/*` (key odds rows on matchId, not team strings).
- `scoring/lambda_handler.py` — writes back under the invoked matchId; ensure
  `scripts/score_round.py` / orchestrator always pass the canonical slug.

**Consumers → round-aware (already true in v1)**
- `api/predictions.py` — keep as-is; **document** the round-aware contract so it isn't "fixed" into
  a round-blind join later.
- v1 has no round-blind joiner equivalent to the v2 inspector; if one is added, it must be round-aware.

## v1-specific risk: it's low, but the cleanup is shared

Because the v1 API is already safe, v1 needs **no urgent change** for correctness. The value is:
1. **Hardening** — a single helper + writer tests so a future v1 writer can't emit a non-canonical
   key and silently break `scoring`'s lookup.
2. **Shared cleanup coordination** — the legacy rows live in the `results` table shared with v2.
   Deleting them (master plan Option A) is a one-time action that benefits both repos; v1 must
   confirm its API/scoring still pass against the cleaned table (they will — they only use
   roundNumber-tagged rows).

## Sequencing (v1)

1. Promote `slug_from_match_centre_url` to the shared matchId helper; route v1 writers through it.
   Add writer regression tests. No behaviour change.
2. Document the round-aware-join invariant in `api/predictions.py` + `CLAUDE.md`.
3. Participate in the **shared dry-run** (master plan steps 4–5): confirm every deletion candidate
   has a canonical counterpart, then back up + delete. Re-run v1's API/scoring acceptance after.

## Tests / docs (v1)

- Helper unit tests: round-N URLs, finals, trailing slash, 2-segment fallback; no home/away reorder.
- Writer regression (moto): results/draw/team_sheet/odds emit `round-N-…` keys.
- **API contract test**: an unplayed round returns predictions with **no** result joined (locks in
  round-awareness — the v1 analogue of the round-17 regression).
- `CLAUDE.md` (v1): "Match identity" note — canonical matchId format, single helper, round-aware
  joins only.

## Recommendation

Lowest-urgency of the four plans: v1's live site is already correct. Do the **hardening** (single
helper + tests + documented invariant) opportunistically alongside the team-slug work, and fold the
**shared row cleanup** into the one coordinated migration so it's done once for both repos. No live
deploy is required for correctness — only to ship the hardening.

## Relationship to the v1 team-slug plan

Compose in the matchId: team slugs give `sea-eagles`; match identity gives `round-16-<home>-v-<away>`.
Land the team registry first so the matchId helper builds slugs from it; otherwise independent.
