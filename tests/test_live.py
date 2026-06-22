"""
Live tests - require real API keys.
Run manually only:
    pytest -m live
Never runs in CI.
"""
import os
import pytest


pytestmark = pytest.mark.live


@pytest.fixture(autouse=True)
def require_api_keys():
    if not os.environ.get("GROQ_API_KEY"):
        pytest.skip("GROQ_API_KEY not set - skipping live test")


def test_live_groq_70b_returns_valid_fsd():
    from src.llm_router import call_llm
    prompt = (
        "Generate a minimal CRS FSD JSON for United Kingdom, Depository Institution. "
        "Return the five keys: summary, architecture, field_catalog, downstream, risk_flags."
    )
    result, attr, status = call_llm(prompt)
    assert result is not None, f"Live call failed. Status: {status}"
    for key in ["summary", "architecture", "field_catalog", "downstream", "risk_flags"]:
        assert key in result, f"Missing key: {key}"
    assert len(result["summary"]) > 100


def test_live_gemini_returns_valid_fsd():
    if not os.environ.get("GEMINI_API_KEY"):
        pytest.skip("GEMINI_API_KEY not set")
    from src.llm_router import _call_gemini
    prompt = (
        "Generate a minimal CRS FSD JSON for Singapore, Custodial Institution. "
        "Return five keys: summary, architecture, field_catalog, downstream, risk_flags."
    )
    result = _call_gemini(prompt)
    assert result is not None
    assert "summary" in result


def test_live_full_generation_uk_depository():
    from src.fsd_generator import generate_fsd
    from src.docx_builder import build_docx
    import os as _os
    params = {
        "fi_type": "Depository Institution",
        "jurisdiction": "United Kingdom",
        "upstream_sources": ["Core Banking System"],
        "account_types": ["Individual accounts", "Entity accounts"],
        "reporting_year": 2024,
        "de_minimis": False,
        "group_fi": False,
    }
    result = generate_fsd(params, None)
    assert "unavailable" not in result["summary"].lower()
    path = build_docx(result, params)
    assert _os.path.exists(path)
    assert _os.path.getsize(path) > 2048
    print(f"\nLive FSD generated: {path}")
    print(f"Attribution: {result.get('attribution')}")
