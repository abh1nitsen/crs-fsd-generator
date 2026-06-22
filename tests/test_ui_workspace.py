"""Static regression checks for the CRS Blueprint workspace UI."""
from pathlib import Path

import pytest


pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "app.py").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")


def test_locked_brand_promise_and_review_banner_are_present():
    normalized = " ".join(APP.split())
    assert "Turn CRS obligations into implementation-ready requirements." in APP
    assert "<strong>Important</strong>" in APP
    assert "Verify jurisdiction-specific requirements against official guidance before use." in normalized


def test_promotional_header_copy_is_removed():
    header = APP[APP.index("with gr.Row(elem_classes=[\"crs-header\"])"):APP.index("with gr.Row(equal_height=False, elem_id=\"workspace-grid\")")]
    assert "No login required" not in header
    assert "Built by" not in header
    assert "Free" not in header


def test_grouped_result_workspace_is_present():
    for label in (
        "Overview",
        "Data & Architecture",
        "Compliance Rules",
        "Controls & Testing",
        "Evidence & Assumptions",
    ):
        assert 'gr.Tab("' + label + '")' in APP


def test_workspace_layout_and_sticky_action_are_present():
    assert 'elem_id="input-wizard"' in APP
    assert 'elem_id="results-workspace"' in APP
    assert 'elem_id="generate-action"' in APP
    assert "position: sticky" in APP


def test_enriched_jurisdiction_explanation_is_present():
    assert "Enriched jurisdictions include enhanced local CRS, FATCA, TIN and submission guidance" in APP
    assert "def jurisdiction_info_html" in APP


def test_stale_fsd_progress_copy_is_absent():
    combined = APP + "\n" + README
    assert "FSD in progress" not in combined
    assert "Generating FSD" not in combined


def test_readme_uses_locked_positioning():
    assert "# CRS Blueprint" in README
    assert "Turn CRS obligations into implementation-ready requirements." in README
    assert "Free. No login required." not in README


def test_wide_table_scroll_wrapper_is_present():
    assert "def _wrap_tables_for_ui" in APP
    assert "table-scroll" in APP
    assert "Wide table — scroll sideways to view all columns" in APP
    assert "min-width: 1080px" in APP


def test_generation_diagnostics_are_collapsible_and_contact_line_is_simple():
    assert "Generation diagnostics" in APP
    assert 'gr.Accordion("Generation diagnostics", open=False)' in APP
    assert "CRS Blueprint &middot; Contact" in APP
    assert "Abhinit Sen</a> for custom requirements" in APP
    assert "Need this mapped to your actual systems?" not in APP
    assert "for a Blueprint Review" not in APP
    assert "Download Implementation Workbook (.xlsx)" in APP
    assert "Document quality gate" not in APP


def test_enterprise_palette_and_table_header_scroll_fix_are_present():
    assert "--crs-indigo: #1d4ed8" in APP
    assert 'primary_hue="blue"' in APP
    assert "border-collapse: separate" in APP
    assert "background: #f1f5f9 !important" in APP
    assert "background-clip: padding-box" in APP
    assert ".fsd-content thead th:first-child" in APP
    assert "simple-cta" not in APP
