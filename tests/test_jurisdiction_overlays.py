"""Regression checks for jurisdiction implementation overlays."""
import json
import re
from pathlib import Path
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
OVERLAY_DIR = ROOT / "kb" / "implementation_overlays"
ENRICHED_CODES = {"au", "gb", "de", "fr", "lu", "ch", "sg", "hk", "ae", "nl", "jp"}


def _load(code: str) -> dict:
    return json.loads((OVERLAY_DIR / f"{code}.json").read_text(encoding="utf-8"))


def test_all_enriched_jurisdictions_have_tin_nil_and_self_cert_overlays():
    files = {p.stem for p in OVERLAY_DIR.glob("*.json")}
    assert ENRICHED_CODES <= files
    for code in ENRICHED_CODES:
        data = _load(code)
        assert data["tin"]["local_label"]
        assert data["tin"]["missing_data_action"]
        assert data["tin"]["default_allowed"] is False
        assert data["nil_reporting"]["state"]
        assert data["self_certification"]["validity_rule"]
        assert data["material_differences"]


def test_tin_regexes_compile_and_examples_match():
    for code in ENRICHED_CODES:
        tin = _load(code)["tin"]
        pattern = re.compile(tin["regex"])
        for example in tin.get("valid_examples", []):
            assert pattern.fullmatch(example), f"{code} example does not match regex: {example}"


def test_overlay_changes_rendered_blueprints_by_jurisdiction(sample_params_depository):
    from src.fsd_generator import generate_fsd

    params_fr = dict(sample_params_depository, jurisdiction="France", fatca_toggle=True)
    params_sg = dict(sample_params_depository, jurisdiction="Singapore", fatca_toggle=True)
    with patch("src.fsd_generator.call_llm", return_value=(None, "", "All engines down.")):
        fr = generate_fsd(params_fr, None)
        sg = generate_fsd(params_sg, None)

    assert "NIF/SPI" in fr["field_catalog"]
    assert "NRIC/FIN" in sg["field_catalog"]
    assert "Material jurisdiction-specific implementation differences" in fr["summary"]
    assert fr["summary"] != sg["summary"]
    assert "Source Layer" in fr["field_catalog"]
    assert "Needs verification" in fr["evidence"]
