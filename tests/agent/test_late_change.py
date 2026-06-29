from v1.agent.late_change import is_high_impact_change


def _player(number: int, name: str = "Player"):
    return {"jersey_number": number, "first_name": name, "last_name": "Test", "is_starting": True}


def _sheet(home_players, away_players=None):
    return {
        "homePlayers": home_players,
        "awayPlayers": away_players or [],
    }


def test_halfback_change_is_high_impact():
    old = _sheet([_player(7, "OldHalf")])
    new = _sheet([_player(7, "NewHalf")])
    assert is_high_impact_change(old, new) is True


def test_hooker_change_is_high_impact():
    old = _sheet([_player(9, "OldHook")])
    new = _sheet([_player(9, "NewHook")])
    assert is_high_impact_change(old, new) is True


def test_fullback_change_is_high_impact():
    old = _sheet([_player(1, "OldFullback")])
    new = _sheet([_player(1, "NewFullback")])
    assert is_high_impact_change(old, new) is True


def test_five_eighth_change_is_high_impact():
    old = _sheet([_player(6, "OldFive")])
    new = _sheet([_player(6, "NewFive")])
    assert is_high_impact_change(old, new) is True


def test_interchange_swap_is_not_high_impact():
    base = [_player(1), _player(7, "Same"), _player(9, "Same")]
    old = _sheet(base + [_player(14, "OldInterchange")])
    new = _sheet(base + [_player(14, "NewInterchange")])
    assert is_high_impact_change(old, new) is False


def test_no_change_is_not_high_impact():
    players = [_player(7), _player(9)]
    sheet = _sheet(players)
    assert is_high_impact_change(sheet, sheet) is False
