import pytest
from unittest.mock import MagicMock, patch
from agent.tools.web_search import web_search, ToolError


def _mock_tavily(results):
    client = MagicMock()
    client.search.return_value = {"results": [{"content": r} for r in results]}
    return client


def test_returns_list_of_snippets():
    client = _mock_tavily(["snippet one", "snippet two"])
    results = web_search("NRL Panthers injury", client=client)
    assert results == ["snippet one", "snippet two"]


def test_raises_tool_error_on_exception():
    client = MagicMock()
    client.search.side_effect = Exception("API unavailable")
    with pytest.raises(ToolError):
        web_search("NRL Panthers injury", client=client)
