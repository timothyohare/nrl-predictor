import json
import os
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("PREDICTIONS_TABLE", "predictions")
    monkeypatch.setenv("RESULTS_TABLE", "results")
    monkeypatch.setenv("RETROSPECTIVES_TABLE", "retrospectives")
    monkeypatch.setenv("MATCH_STATS_TABLE", "match_stats")
    monkeypatch.setenv("ANTHROPIC_SECRET_ARN", "arn:aws:secretsmanager:ap-southeast-2:123:secret:test")
    monkeypatch.setenv("TAVILY_SECRET_ARN", "arn:aws:secretsmanager:ap-southeast-2:123:secret:tavily")


def test_lambda_handler_invokes_retrospective():
    import importlib
    import retrospective.lambda_handler as mod
    importlib.reload(mod)

    with patch("retrospective.lambda_handler.generate_retrospective") as mock_gen, \
         patch("retrospective.lambda_handler.boto3"):
        mock_gen.return_value = {"matchId": "test-match", "verdict": "OK"}
        result = mod.lambda_handler({"matchId": "test-match", "round": 11, "season": 2026}, None)

    mock_gen.assert_called_once()
    call_kwargs = mock_gen.call_args[1]
    assert call_kwargs["match_id"] == "test-match"
    assert call_kwargs["round_number"] == 11
    assert call_kwargs["season"] == 2026
    assert result["matchId"] == "test-match"
