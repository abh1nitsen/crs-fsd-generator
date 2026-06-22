"""Regression tests for Release D/E/F additions."""
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

import pytest

pytestmark = pytest.mark.unit


def test_tin_guidance_is_dedicated_and_jurisdiction_specific(sample_params_depository):
    from src.fsd_generator import load_kb
    from src.implementation_engine import apply_implementation_intelligence
    from src.structured_blueprint import normalise_structured_result, render_section_markdown

    params = dict(sample_params_depository)
    params["jurisdiction"] = "France"
    kb = load_kb("France")
    structured = normalise_structured_result({"summary": "Summary"}, params, kb)
    enriched = apply_implementation_intelligence(structured, params, kb)
    field_md = render_section_markdown(enriched, "field_catalog")
    summary_md = render_section_markdown(enriched, "summary")

    assert "Jurisdiction-specific TIN and identifier guidance" in field_md
    assert "NIF/SPI" in field_md or "SIREN" in field_md
    assert "Default or placeholder TIN allowed" in field_md
    assert "dummy values" in field_md
    assert "Key jurisdiction checks before build lock" in summary_md


def test_source_registry_files_exist_for_enriched_jurisdictions():
    root = Path(__file__).resolve().parents[1]
    for code in ["au", "gb", "de", "fr", "lu", "ch", "sg", "hk", "ae", "nl", "jp"]:
        path = root / "kb" / "source_registry" / f"{code}.json"
        assert path.exists(), f"missing source registry for {code}"
        text = path.read_text(encoding="utf-8")
        assert "registered_official_sources_only" in text
        assert "facts_expected" in text


def test_xlsx_builder_creates_workbook_with_expected_sheets(sample_params_depository, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from src.fsd_generator import generate_fsd
    from src.xlsx_builder import build_xlsx

    params = dict(sample_params_depository)
    params["jurisdiction"] = "France"
    with patch("src.fsd_generator.call_llm", return_value=(None, "", "All engines down.")):
        result = generate_fsd(params, None)
    path = build_xlsx(result, params)
    assert Path(path).exists()
    assert path.endswith(".xlsx")
    with ZipFile(path) as z:
        names = set(z.namelist())
        assert "xl/workbook.xml" in names
        assert "xl/worksheets/sheet1.xml" in names
        workbook_xml = z.read("xl/workbook.xml").decode("utf-8")
        assert "Field Catalogue" in workbook_xml
        assert "TIN Guidance" in workbook_xml


def test_docx_footer_spacing_and_tin_guidance(sample_params_depository, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from src.fsd_generator import generate_fsd
    from src.docx_builder import build_docx

    params = dict(sample_params_depository)
    params["jurisdiction"] = "France"
    with patch("src.fsd_generator.call_llm", return_value=(None, "", "All engines down.")):
        result = generate_fsd(params, None)
    path = build_docx(result, params)
    with ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8")
        assert "Jurisdiction-specific TIN and identifier guidance" in xml
        assert "Pre-download Quality Gate" not in xml
        assert "Draft for professional review" not in xml


def test_static_cta_links_to_linkedin_and_does_not_promise_inactive_action():
    app_text = Path(__file__).resolve().parents[1].joinpath("app.py").read_text(encoding="utf-8")
    docx_text = Path(__file__).resolve().parents[1].joinpath("src", "docx_builder.py").read_text(encoding="utf-8")
    assert "linkedin.com/in/abhinit-sen-63443015" in app_text
    assert "CRS Blueprint &middot; Contact" in app_text
    assert "Abhinit Sen</a> for custom requirements" in app_text
    assert "Abhinit Sen for a Blueprint Review" not in app_text
    assert "Generate a project brief or request a Blueprint Review" not in app_text
    assert "Generate a project brief or request a Blueprint Review" not in docx_text


def test_source_registry_includes_refresh_metadata():
    import json
    root = Path(__file__).resolve().parents[1]
    for code in ["au", "gb", "de", "fr", "lu", "ch", "sg", "hk", "ae", "nl", "jp"]:
        path = root / "kb" / "source_registry" / f"{code}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["kb_refresh_mode"] == "curated_registry_no_runtime_fact_rewrite"
        assert data["refresh_frequency"]
        assert data["last_verified"]
        assert data["technical_refresh_policy"]["auto_rewrite_compliance_facts"] is False
        assert data["technical_refresh_policy"]["runtime_generation_fetch_required"] is False
        assert data["sources"]
        assert all("source_freshness" in src for src in data["sources"])


def test_source_freshness_appears_in_ui_and_evidence(sample_params_depository):
    from src.fsd_generator import load_kb
    from src.implementation_engine import apply_implementation_intelligence
    from src.structured_blueprint import normalise_structured_result, render_section_markdown
    from src.source_health import freshness_from_registry

    root = Path(__file__).resolve().parents[1]
    app_text = root.joinpath("app.py").read_text(encoding="utf-8")
    assert "KB freshness" in app_text
    assert "Source freshness" in app_text

    params = dict(sample_params_depository)
    params["jurisdiction"] = "France"
    kb = load_kb("France")
    freshness = freshness_from_registry(kb.get("_source_registry", {}))
    assert freshness["status"] in {"Fresh", "Review soon", "Stale - review recommended", "Not checked"}

    structured = normalise_structured_result({"summary": "Summary"}, params, kb)
    enriched = apply_implementation_intelligence(structured, params, kb)
    evidence_md = render_section_markdown(enriched, "evidence")
    assert "Refresh / Source Status" in evidence_md
    assert "KB refresh model" in evidence_md
    assert "does not rewrite compliance facts" in evidence_md
