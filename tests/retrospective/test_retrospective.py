import json
from unittest.mock import MagicMock, patch

import pytest

from retrospective.retrospective import generate_retrospective

MATCH_ID = "panthers-v-storm-20260515"


def _make_predictions_table(winner="Panthers", margin=14, confidence="HIGH"):
    table = MagicMock()
    table.query.return_value = {
        "Items": [{
            "matchId": MATCH_ID,
            "generatedAt": "2026-05-15T10:00:00+00:00",
            "predicted_winner": winner,
            "predicted_margin": margin,
            "confidence": confidence,
            "key_factors": ["Cleary's playmaking", "Home advantage", "Storm missing Papenhuyzen"],
            "reasoning": "Panthers look strong at home. Cleary has been dominant. Storm missing spine.",
            "prompt_version": "v1.1",
        }]
    }
    return table


def _make_results_table(home_score=20, away_score=28):
    actual_winner = "Panthers" if home_score > away_score else "Storm"
    table = MagicMock()
    table.query.return_value = {
        "Items": [{
            "matchId": MATCH_ID,
            "scoredAt": "2026-05-15T22:00:00+00:00",
            "homeTeam": "Panthers",
            "awayTeam": "Storm",
            "homeScore": home_score,
            "awayScore": away_score,
            "winner": actual_winner,
            "margin": abs(home_score - away_score),
            "roundNumber": 11,
            "season": 2026,
            "matchState": "FullTime",
        }]
    }
    return table


def _make_retrospectives_table(existing=None):
    table = MagicMock()
    table.query.return_value = {"Items": [existing] if existing else []}
    return table


def _make_match_stats_table():
    return MagicMock()


def _mock_claude_response():
    block = MagicMock()
    block.type = "text"
    block.text = json.dumps({
        "verdict": "Prediction wrong — Storm won by 8 pts, Panthers predicted to win by 14.",
        "hit_factors": ["Cleary did dominate possession but wasn't enough"],
        "missed_factors": ["Storm's defensive structure despite missing Papenhuyzen", "Panthers errors in red zone"],
        "what_actually_happened": "Storm led 14-8 at half-time after two quick tries. Panthers could not convert pressure in the second half.",
        "lesson": "Weight defensive record more heavily; Storm's system is less reliant on individuals.",
    })
    return MagicMock(content=[block])


def test_generate_calls_claude_and_stores(monkeypatch):
    pred_tbl = _make_predictions_table()
    results_tbl = _make_results_table()
    retro_tbl = _make_retrospectives_table()
    stats_tbl = _make_match_stats_table()
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _mock_claude_response()

    with patch("retrospective.retrospective.web_search", return_value=["Storm 28 Panthers 20 match report"]):
        result = generate_retrospective(
            match_id=MATCH_ID,
            round_number=11,
            season=2026,
            predictions_table=pred_tbl,
            results_table=results_tbl,
            retrospectives_table=retro_tbl,
            match_stats_table=stats_tbl,
            anthropic_client=mock_client,
        )

    assert result["verdict"].startswith("Prediction wrong")
    assert "Storm's defensive structure despite missing Papenhuyzen" in result["missed_factors"]
    retro_tbl.put_item.assert_called_once()
    stored = retro_tbl.put_item.call_args[1]["Item"]
    assert stored["matchId"] == MATCH_ID
    assert "generatedAt" in stored
    assert stored["prompt_version"] == "v1.1"


def test_match_stats_stored(monkeypatch):
    pred_tbl = _make_predictions_table()
    results_tbl = _make_results_table()
    retro_tbl = _make_retrospectives_table()
    stats_tbl = _make_match_stats_table()
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _mock_claude_response()

    with patch("retrospective.retrospective.web_search", return_value=["Try scorers: Smith 10, Brown 55"]):
        generate_retrospective(
            match_id=MATCH_ID,
            round_number=11,
            season=2026,
            predictions_table=pred_tbl,
            results_table=results_tbl,
            retrospectives_table=retro_tbl,
            match_stats_table=stats_tbl,
            anthropic_client=mock_client,
        )

    stats_tbl.put_item.assert_called_once()
    stats_item = stats_tbl.put_item.call_args[1]["Item"]
    assert stats_item["matchId"] == MATCH_ID
    assert stats_item["roundNumber"] == 11
    assert "Try scorers: Smith 10, Brown 55" in stats_item["stats"]


def test_skips_if_retrospective_already_exists():
    existing = {"matchId": MATCH_ID, "generatedAt": "2026-05-16T00:00:00Z", "verdict": "Already done"}
    retro_tbl = _make_retrospectives_table(existing=existing)
    mock_client = MagicMock()

    result = generate_retrospective(
        match_id=MATCH_ID,
        round_number=11,
        season=2026,
        predictions_table=MagicMock(),
        results_table=MagicMock(),
        retrospectives_table=retro_tbl,
        match_stats_table=MagicMock(),
        anthropic_client=mock_client,
    )

    mock_client.messages.create.assert_not_called()
    assert result["verdict"] == "Already done"


def test_skips_when_no_ok_prediction():
    """A trailing FAILED prediction row (no predicted_winner) must not crash the
    retrospective — the OK-status filter returns no items, so we skip gracefully."""
    pred_tbl = MagicMock()
    pred_tbl.query.return_value = {"Items": []}  # filter excluded the FAILED row
    retro_tbl = _make_retrospectives_table()
    mock_client = MagicMock()

    result = generate_retrospective(
        match_id=MATCH_ID,
        round_number=11,
        season=2026,
        predictions_table=pred_tbl,
        results_table=MagicMock(),
        retrospectives_table=retro_tbl,
        match_stats_table=MagicMock(),
        anthropic_client=mock_client,
    )

    mock_client.messages.create.assert_not_called()
    assert result == {}


def test_thinking_block_before_text_block():
    """claude-sonnet-4-6 may return a thinking block at content[0] with empty .text;
    the actual JSON is in the text block further along in content[]."""
    pred_tbl = _make_predictions_table()
    results_tbl = _make_results_table()
    retro_tbl = _make_retrospectives_table()
    stats_tbl = _make_match_stats_table()
    mock_client = MagicMock()
    thinking_block = MagicMock()
    thinking_block.type = "thinking"
    thinking_block.text = ""
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = json.dumps({
        "verdict": "Correct pick.",
        "hit_factors": ["Home advantage"],
        "missed_factors": [],
        "what_actually_happened": "Panthers won comfortably.",
        "lesson": "Trust home advantage.",
    })
    mock_client.messages.create.return_value = MagicMock(content=[thinking_block, text_block])

    with patch("retrospective.retrospective.web_search", return_value=[]):
        result = generate_retrospective(
            match_id=MATCH_ID,
            round_number=11,
            season=2026,
            predictions_table=pred_tbl,
            results_table=results_tbl,
            retrospectives_table=retro_tbl,
            match_stats_table=stats_tbl,
            anthropic_client=mock_client,
        )

    assert result["verdict"] == "Correct pick."


def test_web_search_failure_still_completes():
    pred_tbl = _make_predictions_table()
    results_tbl = _make_results_table()
    retro_tbl = _make_retrospectives_table()
    stats_tbl = _make_match_stats_table()
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _mock_claude_response()

    with patch("retrospective.retrospective.web_search", side_effect=Exception("Search failed")):
        result = generate_retrospective(
            match_id=MATCH_ID,
            round_number=11,
            season=2026,
            predictions_table=pred_tbl,
            results_table=results_tbl,
            retrospectives_table=retro_tbl,
            match_stats_table=stats_tbl,
            anthropic_client=mock_client,
        )

    assert "verdict" in result
    mock_client.messages.create.assert_called_once()
