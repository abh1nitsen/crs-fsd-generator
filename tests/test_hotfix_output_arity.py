"""Hotfix regression tests for Gradio output alignment after XLSX export."""
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "app.py").read_text(encoding="utf-8")


def test_success_return_includes_both_download_updates():
    """The success path must return DOCX and XLSX updates before attribution/live outputs."""
    assert "docx_update,\n            xlsx_update,\n            coverage_md" in APP


def test_cached_return_includes_both_download_updates():
    """The cache path must return DOCX and XLSX updates before attribution/live outputs."""
    assert "docx_update_cached,\n                    xlsx_update_cached,\n                    coverage_md" in APP


def test_gradio_output_contract_mentions_sixteen_outputs():
    assert "# 16 outputs:" in APP
    assert "xlsx_download_btn" in APP
    assert "Download Implementation Workbook (.xlsx)" in APP
