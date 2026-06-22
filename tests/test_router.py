"""Tests for llm_router.py - all API calls are mocked."""
import json
import pytest
from unittest.mock import patch, MagicMock


pytestmark = pytest.mark.unit

SAMPLE_PROMPT = "Generate a CRS FSD for United Kingdom, Depository Institution."

MOCK_VALID_RESPONSE = json.dumps({
    "summary": "## Executive Summary\n\nTest summary.",
    "architecture": "## Data Architecture\n\nTest architecture.",
    "field_catalog": "## Field Catalog\n\nTest catalog.",
    "downstream": "## Downstream Reporting\n\nTest downstream.",
    "risk_flags": "## Risk Flags\n\n1. Test risk.",
})


def _mock_groq_completion(content):
    choice = MagicMock()
    choice.message.content = content
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def test_primary_provider_is_tried_first():
    """With weighted routing, one of the two primaries should succeed without touching 8b."""
    from src.llm_router import call_llm
    with patch("src.llm_router._call_groq", return_value=json.loads(MOCK_VALID_RESPONSE)) as mock_groq, \
         patch("src.llm_router._call_gemini", return_value=json.loads(MOCK_VALID_RESPONSE)) as mock_gemini:
        result, attr, status = call_llm(SAMPLE_PROMPT)
    # Either Groq or Gemini was the primary - one should have been called
    assert mock_groq.called or mock_gemini.called
    assert result is not None
    # Groq 8b should NOT have been used as primary succeeded
    if mock_groq.called:
        first_call_model = mock_groq.call_args[0][1] if mock_groq.call_args[0] else ""
        assert "70b" in first_call_model or mock_gemini.called


def test_falls_back_to_gemini_when_groq_rate_limited():
    from src.llm_router import call_llm
    with patch("src.llm_router._call_groq", side_effect=Exception("rate limited")), \
         patch("src.llm_router._call_gemini", return_value=json.loads(MOCK_VALID_RESPONSE)):
        result, attr, status = call_llm(SAMPLE_PROMPT)
    assert result is not None
    assert "gemini" in attr.lower()


def test_falls_back_to_groq_8b_when_gemini_fails():
    from src.llm_router import call_llm

    call_count = {"n": 0}
    def groq_side_effect(prompt, model):
        call_count["n"] += 1
        if "70b" in model:
            raise Exception("rate limited")
        return json.loads(MOCK_VALID_RESPONSE)

    with patch("src.llm_router._call_groq", side_effect=groq_side_effect), \
         patch("src.llm_router._call_gemini", return_value=None):
        result, attr, status = call_llm(SAMPLE_PROMPT)
    assert result is not None
    assert "8b" in attr


def test_all_providers_fail_returns_none():
    from src.llm_router import call_llm
    with patch("src.llm_router._call_groq", side_effect=Exception("rate limited")), \
         patch("src.llm_router._call_gemini", return_value=None):
        result, attr, status = call_llm(SAMPLE_PROMPT)
    assert result is None
    assert attr == ""
    assert "unavailable" in status.lower() or "try again" in status.lower()


def test_status_callback_called_on_fallback():
    from src.llm_router import call_llm
    import random as _random
    status_received = []
    # Pin to groq-first path so the rate-limit → Gemini fallback always fires
    with patch("src.llm_router._call_groq", side_effect=Exception("rate limited")), \
         patch("src.llm_router._call_gemini", return_value=json.loads(MOCK_VALID_RESPONSE)), \
         patch("src.llm_router.random") as mock_random:
        mock_random.random.return_value = 0.0  # < 0.6 → use_groq_first=True
        call_llm(SAMPLE_PROMPT, status_callback=status_received.append)
    assert len(status_received) > 0
    assert any("gemini" in s.lower() or "capacity" in s.lower() for s in status_received)


def test_result_is_dict_with_expected_keys():
    from src.llm_router import call_llm
    with patch("src.llm_router._call_groq", return_value=json.loads(MOCK_VALID_RESPONSE)):
        result, _, _ = call_llm(SAMPLE_PROMPT)
    assert isinstance(result, dict)
    for key in ["summary", "architecture", "field_catalog", "downstream", "risk_flags"]:
        assert key in result
