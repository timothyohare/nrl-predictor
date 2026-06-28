_HIGH_IMPACT_JERSEYS = {1, 6, 7, 9}  # spine: fullback, five-eighth, halfback, hooker


def is_high_impact_change(old_sheet: dict, new_sheet: dict) -> bool:
    for side in ("homePlayers", "awayPlayers"):
        old_by_num = {p["jersey_number"]: p for p in old_sheet.get(side, [])}
        new_by_num = {p["jersey_number"]: p for p in new_sheet.get(side, [])}
        for jersey in _HIGH_IMPACT_JERSEYS:
            old_p = old_by_num.get(jersey)
            new_p = new_by_num.get(jersey)
            if old_p and new_p:
                old_name = f"{old_p['first_name']} {old_p['last_name']}"
                new_name = f"{new_p['first_name']} {new_p['last_name']}"
                if old_name != new_name:
                    return True
    return False
