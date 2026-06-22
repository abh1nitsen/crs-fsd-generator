"""Tests for docx_builder.py"""
import os
import pytest
from pathlib import Path


pytestmark = pytest.mark.unit


def test_build_docx_creates_file(mock_fsd_response, sample_params_depository, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from src.docx_builder import build_docx
    path = build_docx(mock_fsd_response, sample_params_depository)
    assert os.path.exists(path)
    assert path.endswith(".docx")


def test_build_docx_file_is_nonzero(mock_fsd_response, sample_params_depository, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from src.docx_builder import build_docx
    path = build_docx(mock_fsd_response, sample_params_depository)
    assert os.path.getsize(path) > 1024  # at least 1KB


def test_build_docx_filename_contains_jurisdiction(mock_fsd_response, sample_params_depository, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from src.docx_builder import build_docx
    path = build_docx(mock_fsd_response, sample_params_depository)
    assert "United_Kingdom" in path or "united_kingdom" in path.lower()


def test_build_docx_with_empty_sections(sample_params_depository, tmp_path, monkeypatch):
    """Should not raise even if sections are empty strings."""
    monkeypatch.chdir(tmp_path)
    from src.docx_builder import build_docx
    sparse = {
        "summary": "## Summary\n\nMinimal content.",
        "architecture": "",
        "field_catalog": "",
        "downstream": "",
        "risk_flags": "",
        "attribution": "Groq",
    }
    path = build_docx(sparse, sample_params_depository)
    assert os.path.exists(path)


def test_build_docx_with_table_in_section(mock_fsd_response, sample_params_investment, tmp_path, monkeypatch):
    """Field catalog contains markdown tables - docx builder must handle them."""
    monkeypatch.chdir(tmp_path)
    from src.docx_builder import build_docx
    path = build_docx(mock_fsd_response, sample_params_investment)
    assert os.path.exists(path)
    assert os.path.getsize(path) > 1024
