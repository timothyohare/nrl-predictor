# Team identity (v1) — canonical team slug for the live predictor

**Status:** proposal · **Repo:** `nrl-predictor` (v1, **serves the live site**)
**Master plan:** `nrl-predictor2/docs/team-identity-plan.md` (rationale + full options evaluation)

This is the v1-specific cut: concrete files, and the sequencing that matters because **v1 renders
the public frontend**, so a wrong move shows `wests-tigers` to real users.

## Where v1 stands today

- A boundary resolver already exists: `agent/tools/team_names.py::canonical()`, wired into
  `recent_form` and `head_to_head` (live spike confirmed long names now resolve). This is
  Option B from the master plan — the bug is no longer bleeding, but storage is still mixed.
- Names are stored as the NRL `nickName` (`Sea Eagles`) in `results.homeTeam/awayTeam/winner`,
  ladder `positions[].team`, and team-sheet `homeTeam/awayTeam`. The LLM writes `predicted_winner`
  as free text. The odds API supplies full names, fuzzy-matched in `scrapers/odds/scraper.py`.

## Target

Canonical lowercase slug (`sea-eagles`) everywhere internally; a registry maps inbound→slug and
slug→display. Promote `canonical()` into the shared registry (`to_slug` + `display`).

## v1 file inventory

**Producers → emit slug**
- `scrapers/nrl/results.py` (`home_team/away_team/winner`), `backfill.py`
- `scrapers/nrl/team_sheet.py` (`homeTeam/awayTeam`)
- `scrapers/nrl/draw.py` (teams-table `team`, match home/away)
- `scrapers/nrl/ladder.py` (`positions[].team`)
- `scrapers/odds/scraper.py` (replace bespoke full-name match with `to_slug`)
- `agent/lambda_handler.py` — normalise the agent's `predicted_winner` (and any team field in the
  prediction payload) to slug before `put_item`.

**Consumers → assume slug (keep `to_slug` on the arg as defence)**
- `agent/tools/recent_form.py`, `head_to_head.py` (already), `coaching_matchup.py`,
  `spine_synergy.py`, `ladder.py` position lookup, `trap_game.py`
- `scoring/scorer.py` / `scoring/lambda_handler.py` — `predicted_winner == winner` becomes
  slug-vs-slug; pass both through `to_slug` on read during transition so old rows still score.

**Display → map slug → name at the edge (LIVE — do this before migrating data)**
- `api/predictions.py`: add `homeTeamName`/`awayTeamName`/`predictedWinnerName` via `display()`,
  keep raw slug fields. The frontend must never receive only a slug.
- `frontend/lib/api.ts`, `frontend/components/MatchCard.tsx`: render via a `team_registry.json`
  (display name + logo/colours). This is also the right home for crests.

## v1 sequencing (live-safe)

1. Add the registry (`to_slug`/`display` + `team_registry.json`); replace `canonical()` (alias then
   remove). No behaviour change. `gate-ci` green.
2. **API returns display fields** (`*Name`) alongside slugs — deploy this *before* anything writes
   slugs, so the frontend has a name source ready.
3. **Frontend** switches to `display(slug)` / the `*Name` fields. Deploy + eyeball the live site.
4. Writers emit slugs (scrapers + agent output). New rows slug, old rows mixed; readers tolerate
   both via `to_slug`.
5. Migrate existing rows (shared `scripts/migrate_team_slugs.py`): dry-run → back up → rewrite
   `homeTeam/awayTeam/winner/predicted_winner/positions[].team` → verify zero-diff re-run.
6. Contract: read-side `to_slug` stays only as defence against LLM/odds free text.

> **Shared tables:** `results`/`teams`/`predictions` are shared with v2. Migrating them is a
> **one-time, cross-repo** action — coordinate so both repos' readers tolerate both forms *before*
> the migration runs. Run the migration once; it serves both.

## Tests / docs (v1)

- Registry unit tests (all inbound forms → slug, idempotent/total; `display` covers 17).
- Update fixtures in `tests/agent/test_tool_get_recent_form.py`, `test_tool_get_head_to_head.py`,
  coaching/spine/ladder tests to slugs; keep the long-name regression in
  `tests/agent/test_tool_team_names.py`.
- Scoring test: slug-vs-slug; mixed-format row scores during transition.
- Frontend: `MatchCard` renders display name + logo from a slug.
- `CLAUDE.md` (v1): add the "Team identity" invariant — *no raw name is written or passed; everything
  is `to_slug`'d at the boundary; display only at the API/frontend edge.*

## Recommendation

Registry first (low risk, immediately retires the two ad-hoc resolvers). The **live frontend is the
sensitive surface** — land API display fields + frontend rendering (steps 2–3) before any writer
emits slugs, so users never see a raw slug. Treat the shared-table migration as the one risky step,
coordinated with v2 and gated by a dry-run that resolves 100% of existing values.
