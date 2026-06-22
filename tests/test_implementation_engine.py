"""Regression tests for deterministic implementation intelligence."""
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit


def test_deterministic_implementation_engine_adds_high_value_tables(sample_params_depository):
    from src.implementation_engine import apply_implementation_intelligence
    from src.structured_blueprint import normalise_structured_result

    raw = {"summary": "Summary only"}
    structured = normalise_structured_result(raw, sample_params_depository, {"authority": "HMRC"})
    enriched = apply_implementation_intelligence(structured, sample_params_depository, {"authority": "HMRC"})

    field_blocks = enriched["sections"]["field_catalog"]["blocks"]
    tables = {block.get("title"): block for block in field_blocks if block.get("type") == "table"}
    assert "Implementation field catalogue" in tables
    assert len(tables["Implementation field catalogue"]["rows"]) >= 10
    assert "Derived field and transformation rules" in tables

    evidence_text = str(enriched["sections"]["evidence"])
    assert "Verification task register" in evidence_text
    assert "Confirm client physical source-field mapping" in evidence_text
    assert "Technology Guardrail" in evidence_text


def test_vendor_aware_profiles_are_logical_not_physical_fields(sample_params_depository):
    from src.implementation_engine import apply_implementation_intelligence
    from src.structured_blueprint import normalise_structured_result

    params = dict(sample_params_depository)
    params["upstream_sources"] = ["Murex", "Fenergo", "General Ledger"]
    structured = normalise_structured_result({"summary": "Summary"}, params, {})
    enriched = apply_implementation_intelligence(structured, params, {})
    text = str(enriched)

    assert "Murex" in text
    assert "Fenergo" in text
    assert "Logical aliases only" in text
    assert "not_authoritative_for" not in text  # internal profile key should not leak
    assert "Do not use as source of truth" not in text  # use controlled table wording instead


def test_generate_fsd_falls_back_to_complete_deterministic_blueprint(sample_params_depository):
    from src.fsd_generator import generate_fsd

    params = dict(sample_params_depository)
    params["upstream_sources"] = ["Core Banking System", "Murex", "Fenergo"]
    with patch("src.fsd_generator.call_llm", return_value=(None, "", "All engines down.")):
        result = generate_fsd(params, None)

    assert result["_quality_gate"]["passed"]
    assert result["attribution"] == "Deterministic fallback"
    assert "Implementation field catalogue" in result["field_catalog"]
    assert "System-to-field matrix" in result["architecture"]
    assert "Exception and remediation register" in result["risk_flags"]
    assert "Implementation-grade UAT scenarios" in result["testing"]
    assert "This section was not generated" not in str(result["_structured_blueprint"])


def test_summary_is_action_oriented_and_low_value_legacy_summary_is_removed(sample_params_depository):
    from src.implementation_engine import apply_implementation_intelligence
    from src.structured_blueprint import normalise_structured_result, render_section_markdown

    raw = {
        "summary": "This document outlines the implementation blueprint for CRS compliance.\n\n### Needs local confirmation\n| Item | Current Value | Required Action |\n|---|---|---|\n| Exact filing deadline | Not confirmed | Verify locally |",
    }
    structured = normalise_structured_result(raw, sample_params_depository, {"authority": "HMRC"})
    enriched = apply_implementation_intelligence(structured, sample_params_depository, {"authority": "HMRC"})
    summary = render_section_markdown(enriched, "summary")

    assert "Implementation action map" in summary
    assert "Key implementation decisions to confirm before build lock" in summary
    assert "What Must Be Built / Done" in summary
    assert "This document outlines the implementation blueprint" not in summary
    assert "| Exact filing deadline | Not confirmed | Verify locally" not in summary


def test_low_value_legacy_fragments_are_pruned_when_richer_tables_exist(sample_params_depository):
    from src.implementation_engine import apply_implementation_intelligence
    from src.structured_blueprint import normalise_structured_result, render_section_markdown

    raw = {
        "field_catalog": "### CRS fields\n| XML Element | Requirement State |\n|---|---|\n| ResCountryCode | Mandatory |",
        "risk_flags": "### Exception/remediation register\n| Risk Flag | Remediation Action |\n|---|---|\n| Missing tax residence | Outreach |",
        "testing": "### UAT scenarios\n| Scenario | Expected Output |\n|---|---|\n| Reportable account | CRS report |",
        "governance": "### RACI\n| Task | Responsible |\n|---|---|\n| CRS implementation | Compliance team |",
    }
    structured = normalise_structured_result(raw, sample_params_depository, {})
    enriched = apply_implementation_intelligence(structured, sample_params_depository, {})

    assert "Implementation field catalogue" in render_section_markdown(enriched, "field_catalog")
    assert "### CRS fields" not in render_section_markdown(enriched, "field_catalog")
    assert "### Exception/remediation register" not in render_section_markdown(enriched, "risk_flags")
    assert "### UAT scenarios" not in render_section_markdown(enriched, "testing")
    gov = render_section_markdown(enriched, "governance")
    assert "Implementation RACI" in gov
    assert "Implementation milestone plan" in gov
    assert "| CRS implementation | Compliance team" not in gov
