"""Tests for the knowledge base data files."""
import json
import pytest
from pathlib import Path


pytestmark = pytest.mark.unit

REQUIRED_KEYS = ["country", "code", "authority", "reporting_deadline",
                 "thresholds", "key_dates", "rejection_error_codes"]

DETAILED_JURISDICTIONS = ["gb", "sg", "ae", "jp"]


def test_all_kb_files_parse_as_json(kb_dir):
    for f in kb_dir.glob("*.json"):
        with open(f) as fh:
            data = json.load(fh)
        assert isinstance(data, dict), f"{f.name} is not a JSON object"


def test_all_kb_files_have_required_keys(kb_dir):
    for f in kb_dir.glob("*.json"):
        with open(f) as fh:
            data = json.load(fh)
        for key in ["country", "code", "authority"]:
            assert key in data, f"{f.name} missing required key: '{key}'"


def test_detailed_jurisdictions_have_full_schema(kb_dir):
    """UK, Singapore, UAE, Cayman must have the complete schema."""
    for code in DETAILED_JURISDICTIONS:
        path = kb_dir / f"{code}.json"
        assert path.exists(), f"Detailed KB file missing: {code}.json"
        with open(path) as f:
            data = json.load(f)
        for key in REQUIRED_KEYS:
            assert key in data, f"{code}.json missing key: '{key}'"


def test_jurisdiction_urls_all_have_kb_files(jurisdiction_urls, kb_dir):
    for name, entry in jurisdiction_urls.items():
        kb_file = entry.get("kb_file", "")
        assert kb_file, f"{name} has no kb_file entry"
        assert (kb_dir / kb_file).exists(), f"KB file missing for {name}: {kb_file}"


def test_jurisdiction_urls_all_have_local_url(jurisdiction_urls):
    for name, entry in jurisdiction_urls.items():
        assert entry.get("local_url"), f"{name} missing local_url"


def test_no_em_dashes_in_kb_files(kb_dir):
    """No em dashes allowed - house style."""
    for f in kb_dir.glob("*.json"):
        text = f.read_text(encoding="utf-8")
        assert "—" not in text, f"{f.name} contains an em dash"


def test_reporting_deadline_is_a_string(kb_dir):
    for f in kb_dir.glob("*.json"):
        with open(f) as fh:
            data = json.load(fh)
        if "reporting_deadline" in data:
            assert isinstance(data["reporting_deadline"], str), \
                f"{f.name}: reporting_deadline must be a string"
