import json
from unittest.mock import MagicMock

from scrapers.articles.haiku_extractor import extract_injury_mentions
from scrapers.shared.models import InjuryMention

_ARTICLE = "Payne Haas has been ruled out for two weeks with a calf strain. Nathan Cleary is listed as a certain starter."

_VALID_RESPONSE = json.dumps([
    {"player": "Payne Haas", "team": "Broncos", "status": "out", "detail": "calf strain, two weeks"},
    {"player": "Nathan Cleary", "team": "Panthers", "status": "available", "detail": "certain starter"},
])


def _mock_client(content: str):
    client = MagicMock()
    msg = MagicMock()
    msg.content = [MagicMock(text=content)]
    client.messages.create.return_value = msg
    return client


def test_returns_list_of_injury_mentions():
    client = _mock_client(_VALID_RESPONSE)
    results = extract_injury_mentions(_ARTICLE, client)
    assert all(isinstance(r, InjuryMention) for r in results)
    assert len(results) == 2


def test_maps_fields_correctly():
    client = _mock_client(_VALID_RESPONSE)
    results = extract_injury_mentions(_ARTICLE, client)
    haas = next(r for r in results if r.player == "Payne Haas")
    assert haas.team == "Broncos"
    assert haas.status == "out"
    assert "calf" in haas.detail


def test_returns_empty_list_on_malformed_json():
    client = _mock_client("this is not JSON")
    results = extract_injury_mentions(_ARTICLE, client)
    assert results == []


def test_returns_empty_list_on_empty_array():
    client = _mock_client("[]")
    results = extract_injury_mentions(_ARTICLE, client)
    assert results == []


def test_uses_haiku_model():
    client = _mock_client(_VALID_RESPONSE)
    extract_injury_mentions(_ARTICLE, client)
    call_kwargs = client.messages.create.call_args.kwargs
    assert "haiku" in call_kwargs["model"]
