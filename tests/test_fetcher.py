"""Tests for doc_fetcher.py - all HTTP calls are mocked."""
import pytest
from unittest.mock import patch, MagicMock


pytestmark = pytest.mark.unit


SAMPLE_HTML = "<html><body><p>CRS guidance text for testing. " + "word " * 100 + "</p></body></html>"
SAMPLE_JURISDICTION_URLS = {
    "United Kingdom": {
        "code": "GB",
        "kb_file": "gb.json",
        "local_url": "https://www.gov.uk/guidance/common-reporting-standard",
        "oecd_url": "https://www.oecd.org/tax/aeoi/uk.htm",
    }
}


def _make_response(status=200, text=SAMPLE_HTML, content_type="text/html"):
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    resp.content = text.encode()
    resp.headers = {"content-type": content_type}
    resp.raise_for_status = MagicMock()
    return resp


def test_successful_fetch_returns_text():
    from src.doc_fetcher import fetch_latest_guidance
    with patch("src.doc_fetcher.requests.get", return_value=_make_response()):
        text, status = fetch_latest_guidance("United Kingdom", SAMPLE_JURISDICTION_URLS)
    assert text is not None
    assert len(text) > 50


def test_fetch_returns_status_message_on_success():
    from src.doc_fetcher import fetch_latest_guidance
    with patch("src.doc_fetcher.requests.get", return_value=_make_response()):
        text, status = fetch_latest_guidance("United Kingdom", SAMPLE_JURISDICTION_URLS)
    assert "fetched" in status.lower() or "live" in status.lower()


def test_fetch_retries_three_times_then_falls_back():
    from src.doc_fetcher import fetch_latest_guidance
    with patch("src.doc_fetcher.requests.get", side_effect=Exception("timeout")):
        with patch("src.doc_fetcher.time.sleep"):  # skip actual sleep in tests
            text, status = fetch_latest_guidance("United Kingdom", SAMPLE_JURISDICTION_URLS)
    assert text is None
    assert "knowledge base" in status.lower() or "falling back" in status.lower()


def test_unknown_jurisdiction_returns_none():
    from src.doc_fetcher import fetch_latest_guidance
    text, status = fetch_latest_guidance("Atlantis", SAMPLE_JURISDICTION_URLS)
    assert text is None
    assert "no source" in status.lower() or "url" in status.lower()


def test_short_response_treated_as_failure():
    """A response with less than 300 chars is considered empty."""
    from src.doc_fetcher import fetch_latest_guidance
    resp = _make_response(text="<html><body>Loading...</body></html>")
    with patch("src.doc_fetcher.requests.get", return_value=resp):
        with patch("src.doc_fetcher.time.sleep"):
            text, status = fetch_latest_guidance("United Kingdom", SAMPLE_JURISDICTION_URLS)
    assert text is None


def test_http_error_triggers_retry():
    from src.doc_fetcher import fetch_latest_guidance
    resp = _make_response(status=503)
    resp.raise_for_status.side_effect = Exception("503 Server Error")
    with patch("src.doc_fetcher.requests.get", return_value=resp):
        with patch("src.doc_fetcher.time.sleep"):
            text, status = fetch_latest_guidance("United Kingdom", SAMPLE_JURISDICTION_URLS)
    assert text is None
