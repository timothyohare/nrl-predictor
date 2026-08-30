"""Team-sheet spine-position comparison. Shared by the agent's model-selection
heuristic and the orchestrator's spine-disruption signal for `stats-elo-v1`
(docs/plans/11-team-sheet-injury-weather-signals.md). Formerly
`v1/agent/late_change.py` — moved here since both v1 and the stats model need
it; shared logic is edited once at the root, never copied.
"""
from __future__ import annotations

HIGH_IMPACT_JERSEYS = {1, 6, 7, 9}  # spine: fullback, five-eighth, halfback, hooker


def changed_spine_positions(old_sheet: dict, new_sheet: dict, side: str) -> list[int]:
    """Spine jersey numbers (sorted) whose named player differs between
    `old_sheet` and `new_sheet` for one `side` ("homePlayers"/"awayPlayers").

    A jersey missing from either sheet is not a "change" — only a like-for-like
    swap of the *named* player counts, matching `is_high_impact_change`'s
    original behavior.
    """
    old_by_num = {p["jersey_number"]: p for p in old_sheet.get(side, [])}
    new_by_num = {p["jersey_number"]: p for p in new_sheet.get(side, [])}
    changed = []
    for jersey in sorted(HIGH_IMPACT_JERSEYS):
        old_p = old_by_num.get(jersey)
        new_p = new_by_num.get(jersey)
        if old_p and new_p:
            old_name = f"{old_p['first_name']} {old_p['last_name']}"
            new_name = f"{new_p['first_name']} {new_p['last_name']}"
            if old_name != new_name:
                changed.append(jersey)
    return changed


def is_high_impact_change(old_sheet: dict, new_sheet: dict) -> bool:
    """True if either side's spine changed at all between the two sheets."""
    return bool(changed_spine_positions(old_sheet, new_sheet, "homePlayers")) or bool(
        changed_spine_positions(old_sheet, new_sheet, "awayPlayers")
    )


# Provisional — no backtest data exists for this signal (team-sheet history was
# overwritten in place before the diff-on-write in v1/orchestrator/lambda_handler.py
# started collecting it), so this is a placeholder, not a fit constant. Refit in
# Phase 5 of docs/plans/11-team-sheet-injury-weather-signals.md once enough
# post-cutover rounds have accumulated spine_changed flags alongside results.
PROVISIONAL_SPINE_DISRUPTION_PENALTY = -25.0  # Elo points


def spine_disruption_adjustment(spine_changed: bool) -> float:
    """Effective-rating adjustment for one side, given its `spine_changed_*`
    flag off the `teams` table. 0.0 (inert) when the flag is False/missing —
    callers should treat a missing flag the same as False, never as an error.
    """
    return PROVISIONAL_SPINE_DISRUPTION_PENALTY if spine_changed else 0.0
