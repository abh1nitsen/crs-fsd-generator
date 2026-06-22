"""Integration tests: full generation flow with mocked LLMs."""
import json
import pytest
from unittest.mock import patch


pytestmark = pytest.mark.integration


def test_full_flow_uk_depository(mock_fsd_response, sample_params_depository, tmp_cache_dir):
    """End-to-end: params in, FSD sections out, docx created."""
    from src.fsd_generator import generate_fsd
    from src.docx_builder import build_docx

    with patch("src.fsd_generator.call_llm", return_value=(mock_fsd_response, "Groq 70b", "FSD generated.")):
        result = generate_fsd(sample_params_depository, None)

    assert result["summary"].startswith("##")
    assert "HMRC" in result["summary"] or "United Kingdom" in result["summary"]

    path = build_docx(result, sample_params_depository)
    import os
    assert os.path.exists(path)


def test_full_flow_cayman_investment(mock_fsd_response, sample_params_investment, tmp_cache_dir):
    from src.fsd_generator import generate_fsd
    from src.docx_builder import build_docx

    with patch("src.fsd_generator.call_llm", return_value=(mock_fsd_response, "Gemini Flash", "FSD generated.")):
        result = generate_fsd(sample_params_investment, None)

    assert result["attribution"] == "Gemini Flash"
    path = build_docx(result, sample_params_investment)
    import os
    assert os.path.exists(path)


def test_cache_is_written_and_read_back(mock_fsd_response, sample_params_depository, tmp_cache_dir):
    from src.fsd_generator import generate_fsd
    from src.cache_manager import get_cache, set_cache

    with patch("src.fsd_generator.call_llm", return_value=(mock_fsd_response, "Groq 70b", "FSD generated.")):
        result = generate_fsd(sample_params_depository, None)

    cache_key = f"{sample_params_depository['jurisdiction']}_{sample_params_depository['fi_type']}"
    set_cache(cache_key, result)
    cached = get_cache(cache_key)

    assert cached is not None
    assert cached["summary"] == result["summary"]


def test_live_fetch_supplement_included_in_prompt(sample_params_depository, tmp_cache_dir):
    from src.fsd_generator import _build_prompt
    live_text = "LIVE: HMRC updated guidance for 2025 - new threshold of GBP 1,500,000."
    prompt = _build_prompt(sample_params_depository, {}, live_text)
    assert "LIVE" in prompt
    assert "1,500,000" in prompt


def test_all_fi_types_produce_valid_prompt(jurisdiction_urls, tmp_cache_dir):
    """Every FI type + first jurisdiction produces a non-empty prompt."""
    from src.fsd_generator import _build_prompt, _load_kb

    fi_types = [
        "Depository Institution",
        "Custodial Institution",
        "Investment Entity (Type A) - Managed by another FI",
        "Investment Entity (Type B) - Not managed by another FI",
        "Specified Insurance Company",
        "Non-Reporting Financial Institution",
    ]
    for fi in fi_types:
        params = {
            "fi_type": fi,
            "jurisdiction": "United Kingdom",
            "upstream_sources": ["Core Banking System"],
            "account_types": ["Individual accounts"],
            "reporting_year": 2024,
            "de_minimis": False,
            "group_fi": False,
        }
        kb = _load_kb("United Kingdom")
        prompt = _build_prompt(params, kb, None)
        assert fi in prompt, f"FI type '{fi}' not found in prompt"
        assert len(prompt) > 500


def test_all_30_jurisdictions_have_kb_file(jurisdiction_urls, kb_dir):
    """Every entry in jurisdiction_urls.json must have a corresponding KB file."""
    for name, entry in jurisdiction_urls.items():
        kb_file = entry.get("kb_file", "")
        path = kb_dir / kb_file
        assert path.exists(), f"Missing KB file for {name}: {kb_file}"
