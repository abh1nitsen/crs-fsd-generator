"""Shared fixtures and configuration for the CRS Blueprint test suite."""
import json
import os
import tempfile
import pytest
from pathlib import Path
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Sample parameters
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_params_depository():
    return {
        "fi_type": "Depository Institution",
        "jurisdiction": "United Kingdom",
        "upstream_sources": ["Core Banking System", "KYC / AML System"],
        "account_types": ["Individual accounts", "Entity accounts"],
        "reporting_year": 2024,
        "de_minimis": False,
        "group_fi": False,
    }


@pytest.fixture
def sample_params_investment():
    return {
        "fi_type": "Investment Entity (Type A) - Managed by another FI",
        "jurisdiction": "Cayman Islands",
        "upstream_sources": ["Custody / Securities Platform"],
        "account_types": ["Entity accounts"],
        "reporting_year": 2024,
        "de_minimis": False,
        "group_fi": True,
    }


@pytest.fixture
def sample_params_insurance():
    return {
        "fi_type": "Specified Insurance Company",
        "jurisdiction": "Singapore",
        "upstream_sources": ["Core Banking System", "CRM / Customer Onboarding Platform"],
        "account_types": ["Individual accounts"],
        "reporting_year": 2024,
        "de_minimis": False,
        "group_fi": False,
    }


# ---------------------------------------------------------------------------
# Mock LLM response (what a real LLM would return)
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_fsd_response():
    return {
        "summary": (
            "## Executive Summary\n\n"
            "The United Kingdom operates its CRS regime under HMRC oversight. "
            "Reporting FIs must submit annually by 31 May.\n\n"
            "As a Depository Institution, you are required to identify foreign tax residents "
            "among your account holders and report their account details and income.\n\n"
            "Data must be collected from Core Banking and KYC systems and submitted via HMRC IDES."
        ),
        "architecture": (
            "## Data Architecture\n\n"
            "### Upstream Data Flow\n"
            "Self-certifications collected at account opening feed into the KYC system. "
            "Account balances are sourced from the Core Banking System.\n\n"
            "### System Integration Points\n"
            "| Data Element | Source System |\n"
            "|---|---|\n"
            "| Account balance | Core Banking System |\n"
            "| TIN | KYC / AML System |\n\n"
            "### Data Gaps\n"
            "Place of birth is rarely held in Core Banking and may need to be collected."
        ),
        "field_catalog": (
            "## Field Catalog\n\n"
            "### Data to Fetch from Source Systems\n"
            "| Field | Source System | Format / Notes |\n"
            "|---|---|---|\n"
            "| Account number | Core Banking System | Alphanumeric |\n"
            "| Account balance | Core Banking System | Decimal, GBP |\n"
            "| TIN | KYC / AML System | String |\n\n"
            "### Data to Derive\n"
            "| Derived Field | Derivation Logic | Dependencies |\n"
            "|---|---|---|\n"
            "| Reportability flag | Compare tax residency to participating jurisdictions | Self-cert, KYC |\n"
            "| USD equivalent | Apply HMRC FX rate to GBP balance | Account balance |\n"
        ),
        "downstream": (
            "## Downstream Reporting\n\n"
            "### Reporting Obligations\n"
            "Report to HMRC by 31 May each year for the prior calendar year.\n\n"
            "### XML Schema and File Format\n"
            "OECD CRS XML Schema v2.0. Submit via HMRC IDES portal.\n\n"
            "### Recipient Chain\n"
            "Reporting FI to HMRC to OECD Common Transmission System to partner jurisdictions.\n\n"
            "### Key Dates\n"
            "| Date | Event |\n"
            "|---|---|\n"
            "| 31 December | Account balance snapshot |\n"
            "| 31 May | Reporting deadline |\n"
        ),
        "risk_flags": (
            "## Risk Flags and Common Gaps\n\n"
            "1. **Missing self-certifications** - Accounts opened before CRS without self-cert "
            "must be reviewed. Mitigation: implement a retrospective outreach programme.\n\n"
            "2. **Undocumented accounts** - Accounts where no documentation obtained after "
            "reasonable efforts must be reported with a nil balance. "
            "Mitigation: track and escalate undocumented accounts monthly.\n"
        ),
    }


# ---------------------------------------------------------------------------
# Temp directory fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_cache_dir(tmp_path, monkeypatch):
    """Redirect cache writes to a temp directory."""
    monkeypatch.chdir(tmp_path)
    cache = tmp_path / "cache"
    cache.mkdir()
    return tmp_path


@pytest.fixture
def kb_dir():
    """Return the path to the real KB directory."""
    return Path(__file__).parent.parent / "kb" / "jurisdictions"


@pytest.fixture
def jurisdiction_urls():
    """Load real jurisdiction URLs from kb file."""
    path = Path(__file__).parent.parent / "kb" / "jurisdiction_urls.json"
    with open(path) as f:
        return json.load(f)
