# Plan: Team Sheet, Injury & Weather Signals for stats-elo-v1

## Goal

Extend `stats-elo-v1` (the local Elo + Monte Carlo predictor, `common/stats_model/`,
see `docs/plans/10-elo-monte-carlo-predictor.md`) to factor in three signals it
currently ignores by design: starting-lineup disruption (team sheets), player
availability (the `injuries` table), and match-day conditions (the `weather`
table). All three stay deterministic, data-driven adjustments to the Elo
ratings fed into the Monte Carlo simulation — no LLM call is added to the
prediction path.

## Why This Matters

Plan 10 explicitly deferred this: *"Team-sheet changes... are in scope as a
deterministic rating adjustment; RSS-article injury severity and... are not,
pending a decision after backtest results are in."* `predictor.py`'s reasoning
string currently says outright: *"No team-sheet, injury, weather, or
narrative signal used."* That's an accuracy ceiling, not just a disclaimer —
a team missing its halfback and hooker to injury, or playing in Cyclone-grade
rain, has a materially different expected outcome than its Elo rating alone
implies, and the site currently can't see either.

## Data audit (done this session — informs every phase below)

Before designing constants, checked what history actually exists to fit them
against, the same way plan 10's Phase 1 empirically fit the margin/confidence
constants against a 92-match backtest window (rounds 12-24):

- **`teams` table (team sheets):** full player data exists for rounds 12-26
  (108 rows) — the same window the Elo/margin model was fit against. *But*
  each write uses `teamId=matchId, round=roundNumber` as the key, so every
  new scrape of a round **overwrites** the previous one. The orchestrator
  scrapes team sheets Tue/Thu/Fri/Sat, so only the *last* scrape before each
  round is retained — the intra-week lineup changes (the actual signal we
  want) were never preserved. **There is no retroactive backtest data for a
  spine-disruption signal** — it can only be collected going forward.
- **`injuries` table:** 59 mentions total, oldest from the last few weeks
  only. Nowhere near a 92-match-equivalent sample, and not keyed to specific
  rounds/results in a way that supports a retroactive fit.
- **`weather` table:** 52 rows, earliest `2026-07-16` — covers roughly the
  last 5-6 weeks (~round 20+), not the rounds 12-24 window either.

**Conclusion: none of these three signals can be empirically calibrated the
way the core Elo/margin model was.** All three ship with small, clearly-marked
*provisional* constants and a Phase 5 recalibration step once live data
accumulates — the same pattern plan 10 itself used before Phase 1 (defaults
first, `K_FACTOR`/`DEFAULT_HOME_ADVANTAGE`; fit later).

## Design

All three signals are computed as an **effective-rating adjustment applied
only at predict time** — never written back into the persisted Elo history
(`ratings.py::compute_ratings_as_of` stays untouched, so a team's actual
rating trajectory is never contaminated by a one-off weather day or injury
report). `predictor.py::predict_match` gains optional adjustment inputs,
defaulting to zero/inert so every existing call site keeps working unchanged
until each phase wires it in.

### 1. Team sheet / spine-disruption signal

Since intra-round history isn't retained, fix the write path instead of
trying to reconstruct history: when the orchestrator writes a team sheet
(`v1/orchestrator/lambda_handler.py` step 3), **read the existing item first**
and diff spine positions (jersey 1/6/7/9 — fullback/five-eighth/halfback/hooker,
reusing the logic in `v1/agent/late_change.py::is_high_impact_change`) against
the incoming one. Store `spine_changed_home`/`spine_changed_away` (bool) +
`changed_positions` directly on the write. This both produces the live signal
*and* starts accumulating a labeled dataset (flag + eventual result) for
Phase 5, without any schema/key migration.

`is_high_impact_change` currently lives under `v1/agent/` — it needs to move
to `common/` (e.g. `common/team_sheet.py`) since both `v1/orchestrator` and
`v1/tournament` will need to call it; per CLAUDE.md, shared logic is edited
once at the root, never copied.

### 2. Injury signal

Query `injuries` (pk `injury#{team}#{playerSlug}`) for players appearing in
the match's current team sheet, scoped by team. Player names are
freeform/article-extracted (`InjuryMention.player`) vs. structured
`firstName`/`lastName` on the team sheet — matching is inherently fuzzy.
**Fail toward "no match" on ambiguity, never toward a wrong-player
adjustment.** Take the most recent mention per player before kickoff; a
later "returning"/"available" mention cancels a prior "out"/"doubtful" for
the same player.

Caveat to document explicitly (not a new risk, but worth being honest about):
injury mentions are produced by `scrapers/articles/haiku_extractor.py`, which
calls Claude Haiku — an *existing* dependency, unrelated to this plan, but it
means this signal goes quietly stale (not wrong — just empty) if Anthropic
credit is ever exhausted again. The predictor must treat "no injuries data"
identically to "no adjustment," never as an error.

### 3. Weather signal

Look up `weather` (pk `weather#{venue}`, sk `date`) for the match's venue and
kickoff date. Unlike the other two, weather doesn't tell you *who's better* —
it affects *variance*: heavy rain/wind historically compresses scoring and
makes upsets more likely regardless of the Elo favourite. Model it as a
`_MARGIN_STDEV` widening / mild home-advantage dampening in `simulate.py`,
not a straight Elo shift. A missing forecast (no row for that venue/date) is
the common case for many matches even today — must never block a prediction.

### Reasoning/key_factors honesty

`predictor.py`'s "No team-sheet, injury, weather... signal used" line becomes
conditionally false. The reasoning template must only mention a signal when
its adjustment was actually non-zero for that match — no blanket "all
signals considered" claim, matching the existing style where `key_factors`
already lists only what materially contributed.

## Implementation Steps

### Phase 1 — Plumbing (no behavior change)

- **[TEST]** `tests/common/test_predictor.py` — assert `predict_match`'s
  current output is unchanged with new optional adjustment params defaulted
  to inert (0 / no-op).
- **[CODE]** `common/stats_model/predictor.py` — add
  `home_rating_adjustment: float = 0.0`, `away_rating_adjustment: float = 0.0`,
  `margin_stdev_multiplier: float = 1.0` params; apply before calling
  `simulate_match`; extend `key_factors`/`reasoning` templating to only
  mention a term when its value is non-zero/non-default.

### Phase 2 — Team sheet / spine-disruption — DEPLOYED 2026-08-27, confirmed live

(ships first — only signal with a same-length data window, even though it's prospective-only)

- **[CODE]** move `is_high_impact_change` from `v1/agent/late_change.py` to
  `common/team_sheet.py`; re-export or update the agent's import.
- **[TEST]** `tests/v1/orchestrator/test_lambda_handler.py` — read-before-write
  diff logic: first-ever scrape of a round (no prior item) → no change
  flagged; a later scrape with a different spine player → flagged with the
  correct `changed_positions`.
- **[CODE]** `v1/orchestrator/lambda_handler.py` step 3 — read-before-write +
  store `spine_changed_home`/`spine_changed_away`/`changed_positions`.
- **[CODE]** `v1/orchestrator/stats_predictor.py` + the tournament's
  `stats-elo-v1` runner — read the flags off the `teams` table, apply a
  small **provisional** Elo penalty (placeholder: -25, roughly half a
  typical K-factor update) to the disrupted side, only when the flag is set.
- Explicitly out of scope this phase: reconstructing history for a
  retroactive fit — there isn't any (see data audit above).

**Implementation notes (2026-08-27):** landed as planned, with the diff
logic in `common/team_sheet.py` (`changed_spine_positions`,
`is_high_impact_change`, `spine_disruption_adjustment` — the last holds the
`PROVISIONAL_SPINE_DISRUPTION_PENALTY = -25.0` constant so both call sites
share one placeholder, not two). `v1/orchestrator/lambda_handler.py`'s
team-sheet write step now reads the existing `teams` item before overwriting
it. `predict_round`/`run_stats_variant_for_round` both gained an optional
`teams_table` param defaulting to `None` (fails open — same posture as
Phase 1). No infra/CDK change was needed: the tournament worker Lambda
already had `TEAMS_TABLE` in its env and read IAM granted (added for a
different reason, ahead of this plan). Test coverage:
`tests/common/test_team_sheet.py`, `tests/orchestrator/test_orchestrator.py`
(diff-on-write), `tests/orchestrator/test_stats_predictor.py` and
`tests/tournament/test_stats_variant_runner.py`/`test_worker_lambda.py`
(penalty wiring, both fail-open cases). Full `gate-ci --full` green (626
tests). **DEPLOYED and confirmed live 2026-08-27.** `cdk deploy NrlPredictorStack`
succeeded (asset-only diff, no IAM/env changes). Manually invoked
`nrl-predictor-orchestrator` afterward (`{"season": 2026, "round":
"current"}` → resolved to round 26, 8/8 predicted): the `teams` table now
carries `spine_changed_home`/`spine_changed_away`/`changed_positions` on
every match (all `False`/`[]` this run — no lineup changes since the last
scrape, correctly detected), and the resulting `predictions` rows
(generation 3) still carry the "No team-sheet, injury, weather..."
disclaimer verbatim, confirming the reasoning template only drops that line
when an adjustment actually fires.

### Phase 3 — Injury signal — DEPLOYED 2026-08-27, confirmed live

- **[CODE]** `common/players.py` — best-effort name matching between
  `InjuryMention.player` and team-sheet `firstName`/`lastName`, scoped to
  the team slug; returns no-match rather than a low-confidence guess.
- **[TEST]** stale mention (older than the most recent team sheet scrape) is
  ignored; a later "returning"/"available" mention cancels a prior "out".
- **[CODE]** wire the resolved in/out flag into the same adjustment path as
  Phase 2, as a separate constant and separate `key_factors` line.
- Ship with a small placeholder magnitude — 59 historical mentions isn't
  enough to trust a bigger number yet.

**Implementation notes (2026-08-27):** landed mostly as planned, with one
deliberate simplification: rather than a fully separate `key_factors` entry
per signal, the injury adjustment is summed into the same
`home_rating_adjustment`/`away_rating_adjustment` scalar as Phase 2 and
surfaces through the single generic line Phase 1 already built
("`{team} rating adjusted {N} ahead of kickoff (team sheet/injury signal)`")
— still honest (states an adjustment occurred and its size), just not
attributed to team-sheet vs. injury individually. Splitting that further was
judged not worth the added `predict_match` plumbing at this provisional
stage; revisit in Phase 5 if the combined number turns out to hide something
important. `player_slug()` reuses the exact normalization
`scrapers/articles/lambda_handler.py::_player_slug` already uses, so a
team-sheet full name and an `injuries` pk are comparable without any fuzzy
logic — a mismatch just means "no data," never a guessed wrong player.
`has_spine_player_ruled_out()`/`injury_adjustment()` hold the same fail-open
contract as Phase 2 (`PROVISIONAL_INJURY_PENALTY = -20.0`, separate constant
from the team-sheet one). The injury check only runs when *both*
`teams_table` and `injuries_table` are supplied (it needs the current spine
lineup to know which players to look up).

Test coverage: `tests/common/test_players.py` (11 cases — slug matching,
most-recent-status resolution, stale-mention cutoff, a later "available"
cancelling an earlier "out"), plus wiring tests in
`tests/orchestrator/test_stats_predictor.py`,
`tests/tournament/test_stats_variant_runner.py`, and
`tests/tournament/test_worker_lambda.py` (all with a fail-open case for a
missing table). Full `gate-ci --full` green (642 tests).

One genuine infra change this phase (unlike Phase 2): the main orchestrator
Lambda had no read grant on `injuries` before this — added
`injuries_table.grant_read_data(orchestrator_fn)` in `infra/v1_stack.py`
(the tournament worker already had it, from earlier unrelated work).
Confirmed via `cdk diff` before deploying: exactly one added
`dynamodb:GetItem`/`Query`/`Scan` grant on the orchestrator's role, plus the
usual asset update — no other IAM/env changes.

**DEPLOYED and confirmed live 2026-08-27.** `cdk deploy NrlPredictorStack`
succeeded. Manually invoked `nrl-predictor-orchestrator` afterward (round
26, 8/8 predicted, no errors in CloudWatch logs) — and the signal fired for
real on the first live run: `round-26-panthers-v-bulldogs` generation 4
carries `"bulldogs rating adjusted -20 ahead of kickoff (team sheet/injury
signal)"` in `key_factors`, meaning a genuine `injuries`-table mention
matched a bulldogs spine player. Not a synthetic test case — the first
production evidence this signal does something.

### Phase 4 — Weather signal — DEPLOYED 2026-08-30, confirmed live

- **[TEST]** `tests/common/test_simulate.py` — no forecast row for the
  venue/date → simulation output identical to today (no adjustment); a
  high rain/wind forecast widens `_MARGIN_STDEV` by the (placeholder)
  multiplier.
- **[CODE]** `common/stats_model/simulate.py` — accept an optional
  `margin_stdev_multiplier`; `v1/orchestrator/stats_predictor.py` looks up
  `weather` by venue+date and passes it through.
- Same "ship inert-ish, refit later" posture — 52 rows / ~5 weeks isn't
  enough data yet either.

**Implementation notes (2026-08-28):** `simulate_match`'s
`margin_stdev_multiplier` param was already built in Phase 1 (the shared
plumbing phase), so this phase is entirely new `common/weather.py` plus
wiring — no `simulate.py` change needed this time. `common/weather.py`
holds `is_bad_weather()` (provisional thresholds: rain chance ≥60%, wind
≥40km/h) and `margin_stdev_multiplier_for(weather_table, venue, date)`
(`PROVISIONAL_BAD_WEATHER_MULTIPLIER = 1.3`, fails open to `1.0` on any
missing table/date/row).

The two call sites source venue/date differently: `stats_predictor.py` (the
main path) already holds full `Match` objects with `.venue`/`.kick_off`, so
it calls the lookup directly. `stats_variant_runner.py` (the tournament
path) only gets bare matchId strings, so it recovers venue/kickoff-date from
the `{matchId}#home` draw-entry row `v1/orchestrator/lambda_handler.py`
step 2 already writes for every match — no new scrape, no new table, just
reusing data that was already there. Both are wired through
`worker_lambda.py`.

Test coverage: `tests/common/test_weather.py` (9 cases), plus wiring tests
in `test_stats_predictor.py`, `test_stats_variant_runner.py`, and
`test_worker_lambda.py` (bad-weather case, no-forecast no-op, and
omitted-table backward-compatibility for both call sites). Full
`gate-ci --full` green (657 tests).

Infra: same shape as Phase 3 — the main orchestrator Lambda had no read
grant on `weather` before this (the tournament worker already did, from
earlier work); added `weather_table.grant_read_data(orchestrator_fn)` in
`infra/v1_stack.py`, alongside the Phase 3 injuries grant added in the same
comment block.

**DEPLOYED and confirmed live 2026-08-30.** `cdk diff` before deploying
showed exactly the expected single addition (the `Weather` table ARN on the
orchestrator role's read policy) plus the usual asset update. `cdk deploy
NrlPredictorStack` succeeded; manually invoked `nrl-predictor-orchestrator`
afterward (round 26, 8/8 predicted, no errors in CloudWatch logs). No
`"variance widened"` key_factor appeared on any of the 8 matches — correct
behavior, not a bug: round 26 had already been played by 2026-08-30, and the
`weather` table only holds forward-looking forecasts (most recent dated
~2026-08-28+), so there's no row for a past match's venue/date and the
signal fails open as designed. The injury signal (Phase 3) continued firing
correctly alongside it (3 of 8 matches carried a `"rating adjusted -20"`
line), confirming the two signals compose without interfering. Weather
won't show live evidence of actually firing until it's checked against an
upcoming round with a genuinely bad forecast — worth a spot-check then.

### Phase 5 — Recalibration

Once enough post-cutover rounds have accumulated with all three
flags/values recorded *and* scored against real results — target roughly
the same order of magnitude as the original 92-match Elo/margin backtest
before trusting a refit — rerun `scripts/backtest_elo_model.py` (extended
to read the new fields) to replace every placeholder constant introduced in
Phases 2-4 with an empirically fit one. Until then, all three are explicitly
provisional and should be labeled as such in code comments (matching how
`elo.py`'s `DEFAULT_K_FACTOR`/`DEFAULT_HOME_ADVANTAGE` were provisional
before Phase 1 of plan 10 calibrated them).

## Rollout recommendation

Land Phases 2-4 in the **tournament's `stats-elo-v1` variant first**, not
directly in the main `predictions` path — the same way `stats-elo-v1` itself
was proven in the tournament (plan 10 Phase 2) before the Phase 3 production
cutover. Promote to the main path only after Phase 5 shows a real accuracy
lift over the current unmodified baseline; a provisional, unfit constant is
just as likely to hurt accuracy as help it, and the main site shouldn't
absorb that risk directly.

## Success Criteria

- No prediction ever fails or blocks due to missing signal data — all three
  signals fail open to "no adjustment" (missing team-sheet diff, no injury
  match, no weather row all resolve to inert, never an exception).
- `reasoning`/`key_factors` never claims a signal was used when its
  adjustment was zero.
- No new Claude/Anthropic call is added to the prediction path itself (the
  injuries table's existing Haiku dependency is upstream and unchanged).
- After Phase 5 recalibration: pick-rate accuracy on a held-out window is
  measured against the pre-signal baseline before this is called a net win —
  not assumed at ship time.

## Risks / open questions

- Spine-disruption backtesting is prospective-only (rounds 27+); there is no
  shortcut to recover the overwritten history.
- Weather and injury history are both too short today for a real fit —
  identical "ship provisional, refit later" posture as team sheets, just for
  a different reason (data too recent, not overwritten).
- Injury name-matching is fuzzy by nature; needs a conservative bias toward
  "no match" baked into `common/players.py` from the start, not bolted on
  after a bad match is discovered in production.
- Whether all three eventually justify separate versioned constants (refit
  independently) or one combined "context adjustment" fit jointly is an open
  question for Phase 5, not decided here.
