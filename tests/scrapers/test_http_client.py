from unittest.mock import MagicMock

import pytest
import requests

from scrapers.shared.http_client import (
    DELAY_MAX,
    DELAY_MIN,
    MAX_RETRIES,
    ScraperError,
    get_with_retry,
)


def _mock_response(status_code, text="body"):
    r = MagicMock(spec=requests.Response)
    r.status_code = status_code
    r.text = text
    return r


def test_returns_status_and_body_on_success(mocker):
    session = MagicMock()
    session.get.return_value = _mock_response(200, "hello")
    mocker.patch("time.sleep")

    status, body = get_with_retry("https://example.com", session=session)

    assert status == 200
    assert body == "hello"


def test_retries_on_5xx_then_succeeds(mocker):
    session = MagicMock()
    session.get.side_effect = [
        _mock_response(500),
        _mock_response(500),
        _mock_response(200, "ok"),
    ]
    mocker.patch("time.sleep")

    status, body = get_with_retry("https://example.com", session=session)

    assert status == 200
    assert session.get.call_count == 3


def test_raises_scraper_error_after_max_retries(mocker):
    session = MagicMock()
    session.get.return_value = _mock_response(503)
    mocker.patch("time.sleep")

    with pytest.raises(ScraperError):
        get_with_retry("https://example.com", session=session)

    assert session.get.call_count == MAX_RETRIES


def test_delay_is_applied_between_retries(mocker):
    session = MagicMock()
    session.get.side_effect = [_mock_response(500), _mock_response(200, "ok")]
    sleep_mock = mocker.patch("time.sleep")

    get_with_retry("https://example.com", session=session)

    assert sleep_mock.call_count >= 1
    for c in sleep_mock.call_args_list:
        secs = c.args[0]
        assert DELAY_MIN <= secs <= DELAY_MAX


def test_does_not_retry_on_4xx(mocker):
    session = MagicMock()
    session.get.return_value = _mock_response(404)
    mocker.patch("time.sleep")

    with pytest.raises(ScraperError):
        get_with_retry("https://example.com", session=session)

    assert session.get.call_count == 1


def test_passes_custom_headers(mocker):
    session = MagicMock()
    session.get.return_value = _mock_response(200)
    mocker.patch("time.sleep")

    get_with_retry("https://example.com", headers={"X-Foo": "bar"}, session=session)

    _, kwargs = session.get.call_args
    assert kwargs["headers"]["X-Foo"] == "bar"


def test_default_user_agent_is_set(mocker):
    session = MagicMock()
    session.get.return_value = _mock_response(200)
    mocker.patch("time.sleep")

    get_with_retry("https://example.com", session=session)

    _, kwargs = session.get.call_args
    assert "Mozilla" in kwargs["headers"]["User-Agent"]
