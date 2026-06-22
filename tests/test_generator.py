"""Tests for fsd_generator.py"""
import json
import pytest
from pathlib import Path
from unittest.mock import patch


pytestmark = pytest.mark.unit


def test_load_kb_returns_dict_for_known_jurisdiction(kb_dir, tmp_cache_dir):
    from src.fsd_generator import _load_kb
    result = _load_kb("United Kingdom")
    assert isinstance(result, dict)
    assert result.get("country") == "United Kingdom"


def test_load_kb_returns_empty_for_unknown_jurisdiction(tmp_cache_dir):
    from src.fsd_generator import _load_kb
    result = _load_kb("Atlantis")
    # load_kb always returns meta skeleton; check no real data keys present
    assert result.get("country") is None
    assert result.get("authority") is None


def test_all_30_kb_files_are_valid_json(kb_dir):
    """Every file in kb/jurisdictions/ must parse as valid JSON."""
    files = list(kb_dir.glob("*.json"))
    assert len(files) == 30, f"Expected 30 KB files, found {len(files)}"
    for f in files:
        with open(f) as fh:
            data = json.load(fh)
        assert "country" in data, f"{f.name} missing 'country' key"
        assert "code" in data, f"{f.name} missing 'code' key"


def test_build_prompt_contains_fi_type(sample_params_depository, tmp_cache_dir):
    from src.fsd_generator import _build_prompt
    kb = {"country": "United Kingdom", "authority": "HMRC"}
    prompt = _build_prompt(sample_params_depository, kb, None)
    assert "Depository Institution" in prompt
    assert "United Kingdom" in prompt


def test_build_prompt_contains_upstream_sources(sample_params_depository, tmp_cache_dir):
    from src.fsd_generator import _build_prompt
    kb = {}
    prompt = _build_prompt(sample_params_depository, kb, None)
    assert "Core Banking System" in prompt
    assert "KYC / AML System" in prompt


def test_build_prompt_includes_live_text_when_provided(sample_params_depository, tmp_cache_dir):
    from src.fsd_generator import _build_prompt
    live = "LIVE HMRC GUIDANCE: updated thresholds for 2025."
    prompt = _build_prompt(sample_params_depository, {}, live)
    assert "LIVE HMRC GUIDANCE" in prompt


def test_generate_fsd_returns_all_sections(mock_fsd_response, sample_params_depository, tmp_cache_dir):
    from src.fsd_generator import generate_fsd
    with patch("src.fsd_generator.call_llm", return_value=(mock_fsd_response, "Groq 70b", "FSD generated.")):
        result = generate_fsd(sample_params_depository, None)
    for key in ["summary", "architecture", "field_catalog", "downstream", "risk_flags"]:
        assert key in result
        assert len(result[key]) > 10


def test_generate_fsd_returns_deterministic_success_when_llm_fails(sample_params_depository, tmp_cache_dir):
    from src.fsd_generator import generate_fsd
    with patch("src.fsd_generator.call_llm", return_value=(None, "", "All engines down.")):
        result = generate_fsd(sample_params_depository, None)
    assert result["attribution"] == "Deterministic fallback"
    assert "deterministic CRS implementation rules" in result["status"]
    assert "Implementation field catalogue" in result["field_catalog"]
    assert "try again" not in result["status"].lower()


def test_generate_fsd_attribution_set(mock_fsd_response, sample_params_depository, tmp_cache_dir):
    from src.fsd_generator import generate_fsd
    with patch("src.fsd_generator.call_llm", return_value=(mock_fsd_response, "Groq llama-3.3-70b-versatile", "FSD generated.")):
        result = generate_fsd(sample_params_depository, None)
    assert result["attribution"] == "Groq llama-3.3-70b-versatile"


def test_generate_fsd_missing_section_gets_placeholder(sample_params_depository, tmp_cache_dir):
    from src.fsd_generator import generate_fsd
    incomplete = {"summary": "Summary only"}
    with patch("src.fsd_generator.call_llm", return_value=(incomplete, "Groq", "ok")):
        result = generate_fsd(sample_params_depository, None)
    assert "architecture" in result
    assert len(result["architecture"]) > 0
