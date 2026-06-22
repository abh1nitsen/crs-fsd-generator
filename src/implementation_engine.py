"""Deterministic CRS implementation intelligence.

This module turns a validated high-level blueprint into an implementation pack
for Compliance, Operations, Technology and QA.  It deliberately uses logical
system/field guidance instead of pretending to know client-specific vendor
physical table names.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from .structured_blueprint import safe_text
from .source_health import freshness_from_registry

DEFAULT_STATUS = "Verified"
LOCAL_STATUS = "Needs verification"
USER_STATUS = "User input"
INFERRED_STATUS = "Inferred"


_REPO_DIR = Path(__file__).parent.parent
OVERLAY_DIR = _REPO_DIR / "kb" / "implementation_overlays"
SOURCE_REGISTRY_DIR = _REPO_DIR / "kb" / "source_registry"


def _jurisdiction_code(params: dict, kb: dict) -> str:
    code = safe_text(kb.get("code") or "").lower()
    if code:
        return code
    jur = safe_text(params.get("jurisdiction") or kb.get("country") or "").lower()
    name_to_code = {
        "australia": "au", "united kingdom": "gb", "germany": "de", "france": "fr",
        "luxembourg": "lu", "switzerland": "ch", "singapore": "sg", "hong kong": "hk",
        "united arab emirates": "ae", "netherlands": "nl", "japan": "jp",
    }
    return name_to_code.get(jur, "")


def _load_overlay(params: dict, kb: dict) -> dict[str, Any]:
    code = _jurisdiction_code(params, kb)
    if not code:
        return {}
    path = OVERLAY_DIR / f"{code}.json"
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {}


def _load_source_registry(params: dict, kb: dict) -> dict[str, Any]:
    """Load curated official-source metadata for the selected jurisdiction."""
    registry = dict(kb.get("_source_registry", {}) if isinstance(kb.get("_source_registry"), dict) else {})
    code = _jurisdiction_code(params, kb)
    if code:
        path = SOURCE_REGISTRY_DIR / f"{code}.json"
        try:
            if path.exists():
                extra = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(extra, dict):
                    registry.update(extra)
        except Exception:
            pass
    return registry


def _overlay_status(item: dict | None, fallback: str = LOCAL_STATUS) -> str:
    if not isinstance(item, dict):
        return fallback
    return safe_text(item.get("evidence_status") or fallback) or fallback


def _source_layer(*layers: str) -> str:
    return " + ".join([safe_text(l) for l in layers if safe_text(l)])

VENDOR_DISCLAIMER = (
    "Logical aliases only. Confirm physical table, column and interface names against the client's data "
    "dictionary, vendor configuration and extract specifications before build."
)

SYSTEM_PROFILES: dict[str, dict[str, Any]] = {
    "Core Banking System": {
        "category": "Core banking / deposits platform",
        "system_of_record_for": ["deposit accounts", "account status", "year-end balances", "interest credited"],
        "not_authoritative_for": ["full CRS self-certification content", "entity controlling-person due diligence"],
        "typical_aliases": {
            "account_number": ["ACCOUNT_NO", "ACCT_ID", "IBAN", "CONTRACT_ID"],
            "account_balance": ["EOY_BALANCE", "CLOSING_BALANCE", "LEDGER_BALANCE", "AVAILABLE_BALANCE"],
            "interest_amount": ["INTEREST_PAID", "INT_CREDITED", "YTD_INTEREST"],
        },
        "controls": ["Reconcile account-level balances and interest to finance/GL control totals before XML generation."],
    },
    "Temenos Transact / T24": {
        "category": "Core banking platform",
        "system_of_record_for": ["customer accounts", "deposit balances", "interest events", "account status"],
        "not_authoritative_for": ["final tax residence where KYC/self-certification is maintained outside core banking"],
        "typical_aliases": {
            "customer_id": ["CUSTOMER", "CUST_ID", "CUSTOMER_NO"],
            "account_balance": ["WORKING.BALANCE", "OPEN.ACTUAL.BAL", "CLOSING_BALANCE"],
            "tax_residence": ["TAX_RESIDENCE", "RESIDENCE_COUNTRY", "CRS_COUNTRY"],
        },
        "controls": ["Confirm whether CRS/KYC fields are native, local fields, or sourced from a connected KYC platform."],
    },
    "Oracle Flexcube": {
        "category": "Core banking platform",
        "system_of_record_for": ["accounts", "balances", "interest accrual/payment events"],
        "not_authoritative_for": ["self-certification document reliability unless integrated with KYC workflow"],
        "typical_aliases": {
            "account_number": ["CUST_AC_NO", "ACCOUNT_NO", "CONTRACT_REF_NO"],
            "customer_id": ["CUSTOMER_NO", "CIF_ID", "CUST_NO"],
            "account_balance": ["LCY_BAL", "ACY_BAL", "BOOK_BALANCE"],
        },
        "controls": ["Validate currency and reporting-period cut-off because balances can exist in account and local currency."],
    },
    "Infosys Finacle": {
        "category": "Core banking platform",
        "system_of_record_for": ["deposit/customer accounts", "balances", "interest postings"],
        "not_authoritative_for": ["complete CRS classification if customer tax data is stored in separate KYC tooling"],
        "typical_aliases": {
            "account_number": ["FORACID", "ACID", "ACCOUNT_ID"],
            "customer_id": ["CIF_ID", "CUST_ID"],
            "account_balance": ["CLR_BAL_AMT", "SANCT_LIM", "BALANCE_AMT"],
        },
        "controls": ["Confirm account identifier mapping from core account to CRS reporting account reference."],
    },
    "Avaloq": {
        "category": "Wealth/core banking platform",
        "system_of_record_for": ["client portfolios", "account positions", "cash balances", "securities income"],
        "not_authoritative_for": ["new self-certification validity unless the onboarding/KYC workflow is integrated"],
        "typical_aliases": {
            "portfolio": ["PORTFOLIO_ID", "CLIENT_PORTFOLIO", "RELATIONSHIP_NO"],
            "account_balance": ["PORTFOLIO_VALUE", "CASH_BALANCE", "MARKET_VALUE"],
            "income_amount": ["DIVIDEND", "COUPON", "INTEREST", "CASHFLOW"],
        },
        "controls": ["Reconcile portfolio/account valuation extracts to custody or investment accounting control totals."],
    },
    "Murex": {
        "category": "Trading / treasury / capital markets platform",
        "system_of_record_for": ["positions", "cash flows", "derivative/trading valuations", "counterparty exposure inputs"],
        "not_authoritative_for": ["CRS tax residence", "self-certification status", "controlling-person due diligence"],
        "typical_aliases": {
            "account_balance": ["MARKET_VALUE", "POSITION_VALUE", "NPV", "CASH_BALANCE"],
            "income_amount": ["COUPON", "DIVIDEND", "CASH_FLOW_AMOUNT", "INTEREST_AMOUNT"],
            "counterparty": ["COUNTERPARTY", "CP_ID", "LEGAL_ENTITY"],
        },
        "controls": ["Use Murex for valuations/income where it is the product system, but validate CRS residence and TIN against KYC."],
    },
    "Calypso / Adenza": {
        "category": "Trading, treasury and post-trade platform",
        "system_of_record_for": ["trades", "cashflows", "security positions", "settlement/corporate action events"],
        "not_authoritative_for": ["CRS documentary evidence and self-certification"],
        "typical_aliases": {
            "income_amount": ["CASHFLOW", "COUPON", "DIVIDEND", "INTEREST"],
            "account_balance": ["POSITION_VALUE", "MARKET_VALUE", "BOOK_VALUE"],
            "identifier": ["LE_ID", "COUNTERPARTY_ID", "BOOK"],
        },
        "controls": ["Reconcile product-level cashflows to finance and exclude non-reportable internal books."],
    },
    "CRM / Customer Onboarding Platform": {
        "category": "Customer relationship / onboarding workflow",
        "system_of_record_for": ["customer profile", "relationship manager", "onboarding status", "contact details"],
        "not_authoritative_for": ["financial balances", "income amounts", "formal tax classification unless integrated with KYC"],
        "typical_aliases": {
            "customer_name": ["LEGAL_NAME", "CUSTOMER_NAME", "ACCOUNT_HOLDER_NAME"],
            "address": ["REGISTERED_ADDRESS", "MAILING_ADDRESS", "RESIDENTIAL_ADDRESS"],
            "crm_owner": ["RM_ID", "RELATIONSHIP_MANAGER", "OWNER_ID"],
        },
        "controls": ["Use CRM data for outreach and contact routing; validate CRS tax data against KYC/self-certification records."],
    },
    "Salesforce": {
        "category": "CRM / onboarding workflow",
        "system_of_record_for": ["relationship ownership", "customer communications", "cases/outreach", "onboarding workflow tasks"],
        "not_authoritative_for": ["year-end balance", "official CRS XML amounts", "controlling-person due diligence unless custom fields are validated"],
        "typical_aliases": {
            "customer_id": ["AccountId", "External_Customer_ID__c", "Client_ID__c"],
            "tax_residence": ["Tax_Residence__c", "CRS_Country__c", "Tax_Domicile__c"],
            "self_cert_status": ["Self_Cert_Status__c", "KYC_Status__c", "CRS_Status__c"],
        },
        "controls": ["Confirm custom object/field ownership and prevent CRM-only fields becoming unapproved CRS source of truth."],
    },
    "Microsoft Dynamics CRM": {
        "category": "CRM / onboarding workflow",
        "system_of_record_for": ["customer profile", "relationship ownership", "outreach cases"],
        "not_authoritative_for": ["account balances and reportable income"],
        "typical_aliases": {
            "customer_id": ["accountid", "customerid", "externalclientid"],
            "tax_residence": ["taxresidence", "crscountry", "taxdomicile"],
            "case_status": ["case_status", "crs_remediation_status", "follow_up_status"],
        },
        "controls": ["Use Dynamics for workflow evidence; confirm authoritative tax fields with KYC/Compliance."],
    },
    "KYC / AML System": {
        "category": "KYC / AML / customer due diligence platform",
        "system_of_record_for": ["tax residence", "TIN", "self-certification", "entity classification", "controlling persons"],
        "not_authoritative_for": ["financial balances", "product income"],
        "typical_aliases": {
            "tax_residence": ["TAX_RES_COUNTRY", "CRS_RESIDENCE", "TAX_DOMICILE_COUNTRY"],
            "tin": ["TIN", "TAX_ID", "GIIN_OR_TIN", "LOCAL_TAX_IDENTIFIER"],
            "self_cert_status": ["SELF_CERT_STATUS", "CRS_CERT_STATUS", "CERT_RELIABILITY"],
        },
        "controls": ["Compare self-certification values to AML/KYC indicia and document reasonableness checks."],
    },
    "Fenergo": {
        "category": "CLM / KYC workflow platform",
        "system_of_record_for": ["self-certification workflow", "tax classification", "controlling-person records", "documentary evidence"],
        "not_authoritative_for": ["balances, interest, dividends or gross proceeds"],
        "typical_aliases": {
            "tax_residence": ["Tax Residence", "CRS Country", "Tax Domicile"],
            "tin": ["TIN", "Tax Identification Number", "Tax ID"],
            "entity_classification": ["CRS Classification", "Entity Type", "NFE Classification"],
        },
        "controls": ["Use workflow audit trail as evidence for remediation, approvals and change-in-circumstances review."],
    },
    "Custody / Securities Platform": {
        "category": "Custody / securities platform",
        "system_of_record_for": ["holdings", "security positions", "dividends", "gross proceeds", "custody accounts"],
        "not_authoritative_for": ["tax residence and self-certification unless connected to KYC"],
        "typical_aliases": {
            "holding_value": ["MARKET_VALUE", "POSITION_VALUE", "HOLDING_VALUE"],
            "dividend": ["DIVIDEND_AMOUNT", "CORPORATE_ACTION_CASH", "INCOME_PAYMENT"],
            "gross_proceeds": ["SALE_PROCEEDS", "REDEMPTION_PROCEEDS", "DISPOSAL_VALUE"],
        },
        "controls": ["Reconcile holdings and income to custodian statements or investment accounting ledger."],
    },
    "Fund Administration Platform": {
        "category": "Fund administration / transfer agency platform",
        "system_of_record_for": ["investor register", "units/shares", "subscriptions/redemptions", "investor balances"],
        "not_authoritative_for": ["bank deposit interest", "trading-book valuations"],
        "typical_aliases": {
            "investor_id": ["INVESTOR_ID", "HOLDER_ID", "REGISTER_NO"],
            "balance": ["NAV_VALUE", "HOLDING_VALUE", "UNITS_HELD"],
            "gross_proceeds": ["REDEMPTION_AMOUNT", "DISTRIBUTION_AMOUNT", "SALE_PROCEEDS"],
        },
        "controls": ["Tie CRS investor register to transfer-agent register and NAV valuation date."],
    },
    "Corporate Actions Platform": {
        "category": "Corporate actions / income processing",
        "system_of_record_for": ["dividends", "coupon income", "redemptions", "withholding events"],
        "not_authoritative_for": ["account-holder tax residence"],
        "typical_aliases": {
            "dividend": ["DIVIDEND", "CORP_ACT_CASH", "INCOME_EVENT"],
            "coupon": ["COUPON", "INTEREST_EVENT", "BOND_INTEREST"],
            "security_id": ["ISIN", "CUSIP", "SEDOL", "SECURITY_ID"],
        },
        "controls": ["Reconcile CRS income totals to corporate-action event ledger and custody statements."],
    },
    "General Ledger": {
        "category": "Finance / accounting ledger",
        "system_of_record_for": ["control totals", "ledger reconciliation", "finance sign-off"],
        "not_authoritative_for": ["account-level CRS due diligence or customer tax residence"],
        "typical_aliases": {
            "control_total": ["GL_BALANCE", "TRIAL_BALANCE", "CONTROL_TOTAL"],
            "income_total": ["INTEREST_INCOME", "DIVIDEND_INCOME", "PROCEEDS_TOTAL"],
        },
        "controls": ["Use GL as a completeness and reasonableness control, not as the primary account-level data source."],
    },
    "Enterprise Data Warehouse": {
        "category": "Data warehouse / reporting mart",
        "system_of_record_for": ["conformed extracts", "historical snapshots", "reporting joins", "reconciliation packs"],
        "not_authoritative_for": ["source-system correction unless lineage to origin is retained"],
        "typical_aliases": {
            "customer_key": ["CUSTOMER_KEY", "PARTY_KEY", "CLIENT_SK"],
            "account_key": ["ACCOUNT_KEY", "CONTRACT_KEY", "PRODUCT_ACCOUNT_SK"],
            "snapshot_date": ["SNAPSHOT_DATE", "AS_OF_DATE", "REPORTING_DATE"],
        },
        "controls": ["Retain lineage from warehouse field to original system and snapshot timestamp."],
    },
    "Manual / Spreadsheets": {
        "category": "Manual remediation / spreadsheet control",
        "system_of_record_for": ["temporary remediation overrides", "manual attestations", "gap closure tracking"],
        "not_authoritative_for": ["uncontrolled recurring CRS production without sign-off"],
        "typical_aliases": {
            "override": ["OVERRIDE_VALUE", "MANUAL_FIX", "REMEDIATION_STATUS"],
            "approval": ["APPROVER", "APPROVAL_DATE", "EVIDENCE_LINK"],
        },
        "controls": ["Require maker-checker approval, version control and evidence link for every manual override."],
    },
    "Third-party Data Vendor": {
        "category": "External reference/data provider",
        "system_of_record_for": ["reference data enrichment", "country lists", "exchange rates", "entity identifier enrichment"],
        "not_authoritative_for": ["client self-certification and final FI reporting decision without internal approval"],
        "typical_aliases": {
            "reference_country": ["COUNTRY_CODE", "ISO_COUNTRY", "TAX_JURISDICTION"],
            "fx_rate": ["FX_RATE", "SPOT_RATE", "YEAR_END_RATE"],
        },
        "controls": ["Validate vendor feed version, run date, coverage and exception handling before using in CRS production."],
    },
}

ALIASES = {
    "T24": "Temenos Transact / T24",
    "Temenos": "Temenos Transact / T24",
    "Flexcube": "Oracle Flexcube",
    "Finacle": "Infosys Finacle",
    "Dynamics": "Microsoft Dynamics CRM",
    "Data Warehouse": "Enterprise Data Warehouse",
    "Corporate Actions": "Corporate Actions Platform",
    "Fund Admin": "Fund Administration Platform",
}


def _profile_for(name: str) -> dict[str, Any]:
    canonical = ALIASES.get(name, name)
    return SYSTEM_PROFILES.get(canonical, {
        "category": "User-selected upstream system",
        "system_of_record_for": ["confirm with system owner"],
        "not_authoritative_for": ["do not use as source of truth until lineage is confirmed"],
        "typical_aliases": {},
        "controls": [VENDOR_DISCLAIMER],
    })


def _status_from_kb(value: Any) -> str:
    text = safe_text(value)
    if not text or text.lower() in {"not confirmed", "unknown", "n/a"}:
        return LOCAL_STATUS
    if "[inferred]" in text.lower():
        return INFERRED_STATUS
    return DEFAULT_STATUS


def _selected_systems(params: dict) -> list[str]:
    systems = params.get("upstream_sources") or []
    if not systems:
        systems = ["Core Banking System", "KYC / AML System", "Enterprise Data Warehouse"]
    # Preserve order and remove duplicates.
    seen = set()
    out = []
    for s in systems:
        name = safe_text(s)
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def _systems_hint(kind: str, selected: list[str]) -> str:
    matches: list[str] = []
    if kind == "kyc":
        candidates = ["KYC / AML System", "Fenergo", "CRM / Customer Onboarding Platform", "Salesforce", "Microsoft Dynamics CRM"]
    elif kind == "balance":
        candidates = ["Core Banking System", "Temenos Transact / T24", "Oracle Flexcube", "Infosys Finacle", "Avaloq", "Custody / Securities Platform", "Fund Administration Platform", "Murex", "Calypso / Adenza"]
    elif kind == "income":
        candidates = ["Core Banking System", "Custody / Securities Platform", "Corporate Actions Platform", "Murex", "Calypso / Adenza", "Avaloq", "General Ledger"]
    elif kind == "workflow":
        candidates = ["CRM / Customer Onboarding Platform", "Fenergo", "Salesforce", "Microsoft Dynamics CRM", "Manual / Spreadsheets"]
    else:
        candidates = selected
    for c in candidates:
        if c in selected and c not in matches:
            matches.append(c)
    if not matches:
        matches = candidates[:3]
    return ", ".join(matches)


def _source_profile_rows(params: dict) -> list[dict[str, str]]:
    rows = []
    for system in _selected_systems(params):
        p = _profile_for(system)
        rows.append({
            "System / Platform": system,
            "Typical CRS Use": "; ".join(p.get("system_of_record_for", [])[:4]),
            "Do Not Use Alone For": "; ".join(p.get("not_authoritative_for", [])[:3]),
            "Implementation Control": " ".join(p.get("controls", [])[:1]),
            "Evidence Status": USER_STATUS,
        })
    return rows


def _system_to_field_rows(params: dict) -> list[dict[str, str]]:
    selected = _selected_systems(params)
    rows = [
        {
            "Data Item": "Tax residence country",
            "Authoritative Source": _systems_hint("kyc", selected),
            "Possible Platforms": "Fenergo, Salesforce, Dynamics CRM, KYC repository, onboarding workflow",
            "Fallback / Remediation": "Obtain or refresh self-certification; do not infer tax residence solely from trading or GL data.",
            "Not Acceptable Alone": "Murex counterparty country, GL entity country, mailing country without self-certification reasonableness check",
            "Control": "KYC/self-certification reasonableness check against address, phone, RM knowledge and documentary evidence.",
            "Evidence Status": DEFAULT_STATUS,
        },
        {
            "Data Item": "TIN / local tax identifier",
            "Authoritative Source": _systems_hint("kyc", selected),
            "Possible Platforms": "Fenergo, KYC repository, onboarding workflow, CRM custom CRS fields",
            "Fallback / Remediation": "TIN outreach and reasonable-efforts evidence; use jurisdiction-specific missing-TIN treatment only if verified.",
            "Not Acceptable Alone": "Placeholder values, Unknown, 000000, free-text notes without approved evidence",
            "Control": "Format validation where local format is known; exception report for blank or invalid TIN.",
            "Evidence Status": DEFAULT_STATUS,
        },
        {
            "Data Item": "Closing balance / account value",
            "Authoritative Source": _systems_hint("balance", selected),
            "Possible Platforms": "Temenos, Flexcube, Finacle, Avaloq, Murex, Calypso/Adenza, custody, fund admin, warehouse",
            "Fallback / Remediation": "Use GL/custody control totals only as reconciliation unless account-level lineage is retained.",
            "Not Acceptable Alone": "Manual estimate or stale prior-period balance",
            "Control": "Reconcile account-level total to GL/custody/fund-admin control total for the reporting snapshot date.",
            "Evidence Status": DEFAULT_STATUS,
        },
        {
            "Data Item": "Interest, dividends and gross proceeds",
            "Authoritative Source": _systems_hint("income", selected),
            "Possible Platforms": "Corporate actions, custody, core banking, Murex, Calypso/Adenza, investment accounting, GL",
            "Fallback / Remediation": "Use product/event ledger with finance sign-off; preserve event-level audit trail where available.",
            "Not Acceptable Alone": "CRM notes, unapproved spreadsheet summaries",
            "Control": "Income totals reconcile to finance/product ledger and security-event reports.",
            "Evidence Status": DEFAULT_STATUS,
        },
        {
            "Data Item": "Controlling persons for Passive NFE",
            "Authoritative Source": _systems_hint("kyc", selected),
            "Possible Platforms": "Fenergo, entity KYC repository, onboarding platform, beneficial ownership register",
            "Fallback / Remediation": "Trigger entity remediation and controlling-person outreach; block final classification until resolved.",
            "Not Acceptable Alone": "Trading counterparty contact list, RM notes without KYC approval",
            "Control": "Passive NFE cannot be marked complete unless controlling-person population and tax residences are captured or approved exception exists.",
            "Evidence Status": DEFAULT_STATUS,
        },
    ]
    for row in rows:
        item = safe_text(row.get("Data Item", "")).lower()
        row["Source Layer"] = "Global CRS baseline + System overlay"
        if "tin" in item:
            row["Source Layer"] = "Global CRS baseline + Jurisdiction overlay + System overlay"
    return rows


def _field_catalog_rows(params: dict, kb: dict) -> list[dict[str, str]]:
    selected = _selected_systems(params)
    tax_src = _systems_hint("kyc", selected)
    bal_src = _systems_hint("balance", selected)
    inc_src = _systems_hint("income", selected)
    overlay = _load_overlay(params, kb)
    tin_overlay = overlay.get("tin", {}) if isinstance(overlay.get("tin"), dict) else {}
    self_cert_overlay = overlay.get("self_certification", {}) if isinstance(overlay.get("self_certification"), dict) else {}
    tin_label = safe_text(tin_overlay.get("local_label") or kb.get("tin_label") or kb.get("tin", {}).get("label") or "TIN / local tax identifier")
    tin_format = safe_text(tin_overlay.get("format") or tin_overlay.get("regex") or kb.get("tin_format") or kb.get("tin", {}).get("format") or "Jurisdiction-specific format not confirmed")
    tin_missing = safe_text(tin_overlay.get("missing_data_action") or kb.get("tin_missing_action") or kb.get("tin", {}).get("missing_action") or "Flag for TIN remediation; document reasonable efforts; confirm permitted reporting treatment for the jurisdiction.")
    tin_status = _overlay_status(tin_overlay, _status_from_kb(kb.get("tin_format") or kb.get("tin", {}).get("format")))
    self_cert_rule = safe_text(self_cert_overlay.get("validity_rule") or "Complete and signed self-certification remains usable until a change in circumstances or reliability issue is identified; confirm any jurisdiction-specific refresh rule before build lock.")
    self_cert_status = _overlay_status(self_cert_overlay, LOCAL_STATUS)
    rows = [
        {
            "Field": "Reporting FI identifier",
            "XML Element": "ReportingFI / TIN or local identifier",
            "Requirement": "Mandatory",
            "Source of Record": "Regulatory registration / FI reference data",
            "Typical Logical Aliases": "FI_TIN, GIIN, SIREN, UEN, BUSINESS_ID, REPORTING_FI_ID",
            "Validation / Transformation": "Validate against local FI registration identifier and reporting schema format.",
            "Missing-data Action": "Block submission configuration until identifier is confirmed by Compliance/Tax.",
            "Evidence Status": _status_from_kb(kb.get("msg_ref_id_format") or kb.get("authority")),
        },
        {
            "Field": "Account number / account reference",
            "XML Element": "AccountReport / AccountNumber",
            "Requirement": "Mandatory where reportable account exists",
            "Source of Record": bal_src,
            "Typical Logical Aliases": "ACCOUNT_NO, ACCT_ID, IBAN, CONTRACT_ID, PORTFOLIO_ID",
            "Validation / Transformation": "Use stable reportable account reference; retain mapping to internal account/product identifier.",
            "Missing-data Action": "Raise data-quality exception; do not replace with customer ID unless approved mapping exists.",
            "Evidence Status": DEFAULT_STATUS,
        },
        {
            "Field": "Account holder legal name",
            "XML Element": "AccountHolder / Name",
            "Requirement": "Mandatory",
            "Source of Record": tax_src,
            "Typical Logical Aliases": "LEGAL_NAME, CUSTOMER_NAME, REGISTERED_NAME, ACCOUNT_HOLDER_NAME",
            "Validation / Transformation": "Match KYC legal name; strip unsupported characters only under documented transliteration rule.",
            "Missing-data Action": "Flag for KYC remediation; do not fabricate Unknown or placeholder names.",
            "Evidence Status": DEFAULT_STATUS,
        },
        {
            "Field": "Account holder address",
            "XML Element": "AccountHolder / Address",
            "Requirement": "Mandatory / conditional per schema and account type",
            "Source of Record": tax_src,
            "Typical Logical Aliases": "REGISTERED_ADDRESS, RESIDENTIAL_ADDRESS, MAILING_ADDRESS, ADDRESS_COUNTRY",
            "Validation / Transformation": "Validate country code; preserve line ordering and address type where required.",
            "Missing-data Action": "Route to customer/KYC remediation and block final file until permitted handling is confirmed.",
            "Evidence Status": DEFAULT_STATUS,
        },
        {
            "Field": "Tax residence country",
            "XML Element": "AccountHolder / ResCountryCode",
            "Requirement": "Mandatory for reportability decision",
            "Source of Record": tax_src,
            "Typical Logical Aliases": "TAX_RES_COUNTRY, CRS_RESIDENCE, TAX_DOMICILE_COUNTRY, RES_COUNTRY_CODE",
            "Validation / Transformation": "ISO 3166-1 alpha-2 country code; allow multiple tax residences where self-certification supports them.",
            "Missing-data Action": "Treat as unresolved CRS due-diligence exception; trigger self-certification outreach and Compliance escalation.",
            "Evidence Status": DEFAULT_STATUS,
        },
        {
            "Field": tin_label,
            "XML Element": "AccountHolder / TIN",
            "Requirement": "Mandatory or conditional depending on account holder jurisdiction and local rules",
            "Source of Record": tax_src,
            "Typical Logical Aliases": "TIN, TAX_ID, TAX_NUMBER, LOCAL_TAX_IDENTIFIER, CRS_TIN",
            "Validation / Transformation": "Expected format: " + tin_format + ". Apply local regex only after official format is confirmed.",
            "Missing-data Action": tin_missing,
            "Evidence Status": tin_status,
            "Source Layer": "Global CRS baseline + Jurisdiction overlay",
        },
        {
            "Field": "Date of birth",
            "XML Element": "Individual / BirthInfo / BirthDate",
            "Requirement": "Mandatory for individual account holders where required by schema/local guidance",
            "Source of Record": tax_src,
            "Typical Logical Aliases": "DOB, DATE_OF_BIRTH, BIRTH_DATE",
            "Validation / Transformation": "YYYY-MM-DD; reject future dates and implausible age values for manual review.",
            "Missing-data Action": "KYC remediation; capture outreach evidence and unresolved population report.",
            "Evidence Status": DEFAULT_STATUS,
        },
        {
            "Field": "Entity CRS classification",
            "XML Element": "AccountHolder / AcctHolderType",
            "Requirement": "Mandatory for entity accounts",
            "Source of Record": tax_src,
            "Typical Logical Aliases": "CRS_ENTITY_TYPE, NFE_CLASSIFICATION, ENTITY_CLASS, PASSIVE_NFE_FLAG",
            "Validation / Transformation": "Map local KYC classification to CRS categories; Passive NFE triggers controlling-person extraction.",
            "Missing-data Action": "Block reportability finalisation for entity accounts until classification is completed or approved exception exists.",
            "Evidence Status": DEFAULT_STATUS,
        },
        {
            "Field": "Controlling person details",
            "XML Element": "ControllingPerson / Name, Address, ResCountryCode, TIN, BirthInfo",
            "Requirement": "Conditional: required for Passive NFE and other look-through cases",
            "Source of Record": tax_src,
            "Typical Logical Aliases": "CP_NAME, BENEFICIAL_OWNER, CONTROLLING_PERSON, UBO_TAX_RESIDENCE",
            "Validation / Transformation": "Extract all relevant controlling persons; apply individual validation rules to each controlling person.",
            "Missing-data Action": "Create Passive NFE remediation case; do not suppress account from exception reporting without Compliance approval.",
            "Evidence Status": DEFAULT_STATUS,
        },
        {
            "Field": "Account balance / value",
            "XML Element": "AccountReport / AccountBalance",
            "Requirement": "Mandatory for reportable accounts unless closed-account treatment applies",
            "Source of Record": bal_src,
            "Typical Logical Aliases": "EOY_BALANCE, CLOSING_BALANCE, ACCOUNT_VALUE, MARKET_VALUE, POSITION_VALUE",
            "Validation / Transformation": "Use reporting-period snapshot date; preserve original currency and conversion rate if conversion is applied.",
            "Missing-data Action": "Raise balance exception; do not default to zero unless account is confirmed closed or zero-balance under documented rule.",
            "Evidence Status": DEFAULT_STATUS,
        },
        {
            "Field": "Interest amount",
            "XML Element": "Payment / Type=CRS501 or local equivalent",
            "Requirement": "Conditional: required where interest is paid/credited and reportable under schema",
            "Source of Record": inc_src,
            "Typical Logical Aliases": "INTEREST_PAID, INT_CREDITED, COUPON, INTEREST_AMOUNT",
            "Validation / Transformation": "Aggregate by reportable account and reporting year; exclude reversals only with documented event logic.",
            "Missing-data Action": "Reconcile to product ledger/GL and remediate missing event feed before file creation.",
            "Evidence Status": DEFAULT_STATUS,
        },
        {
            "Field": "Dividend amount",
            "XML Element": "Payment / Type=CRS502 or local equivalent",
            "Requirement": "Conditional: required for relevant custodial/investment accounts",
            "Source of Record": inc_src,
            "Typical Logical Aliases": "DIVIDEND_AMOUNT, INCOME_PAYMENT, CORP_ACT_CASH, DISTRIBUTION_AMOUNT",
            "Validation / Transformation": "Aggregate gross dividends paid or credited during the reporting year by account/security event.",
            "Missing-data Action": "Investigate corporate-action/custody feed gap and retain reconciliation evidence.",
            "Evidence Status": DEFAULT_STATUS,
        },
        {
            "Field": "Gross proceeds",
            "XML Element": "Payment / Type=CRS503 or local equivalent",
            "Requirement": "Conditional: required for custodial sale/redemption proceeds where applicable",
            "Source of Record": inc_src,
            "Typical Logical Aliases": "SALE_PROCEEDS, REDEMPTION_PROCEEDS, DISPOSAL_VALUE, GROSS_PROCEEDS",
            "Validation / Transformation": "Aggregate gross, not net, proceeds by reportable account unless local schema guidance says otherwise.",
            "Missing-data Action": "Raise product/event exception and reconcile to transaction ledger before filing.",
            "Evidence Status": DEFAULT_STATUS,
        },
        {
            "Field": "Account closed indicator",
            "XML Element": "AccountReport / AccountClosed or local equivalent",
            "Requirement": "Conditional",
            "Source of Record": bal_src,
            "Typical Logical Aliases": "ACCOUNT_STATUS, CLOSED_DATE, CLOSURE_FLAG, TERMINATION_DATE",
            "Validation / Transformation": "Set from account lifecycle data; verify whether closing balance should be zero or last known value under local schema guidance.",
            "Missing-data Action": "Remediate account lifecycle status before applying closed-account reporting treatment.",
            "Evidence Status": DEFAULT_STATUS,
        },
        {
            "Field": "Self-certification status and reliability",
            "XML Element": "Due diligence evidence / self-certification metadata",
            "Requirement": "Mandatory implementation control for onboarding, remediation and change-in-circumstances workflows",
            "Source of Record": tax_src,
            "Typical Logical Aliases": "SELF_CERT_STATUS, CRS_CERT_STATUS, CERT_SIGNED_DATE, CERT_RELIABILITY, CHANGE_IN_CIRCUMSTANCES_FLAG",
            "Validation / Transformation": self_cert_rule,
            "Missing-data Action": "Create self-certification remediation task; do not rely on stale or unreliable values without documented Compliance approval.",
            "Evidence Status": self_cert_status,
            "Source Layer": "Global CRS baseline + Jurisdiction overlay",
        },
    ]
    for row in rows:
        if "Source Layer" not in row:
            field = safe_text(row.get("Field", "")).lower()
            if "tin" in field or "tax identifier" in field:
                row["Source Layer"] = "Global CRS baseline + Jurisdiction overlay"
                row["Evidence Status"] = tin_status
            elif "self-cert" in field:
                row["Source Layer"] = "Global CRS baseline + Jurisdiction overlay"
            else:
                row["Source Layer"] = "Global CRS baseline"
    return rows


def _derived_rule_rows(params: dict) -> list[dict[str, str]]:
    return [
        {
            "Derived Rule": "Reportable account flag",
            "Inputs": "Account holder type, tax residence, participating/reportable jurisdiction list, account exclusion status, self-certification reliability, controlling-person data",
            "Implementation Logic": "Set reportable when the account holder or relevant controlling person is tax resident in a reportable jurisdiction and the account is not excluded.",
            "Fallback / Limitation": "If tax residence or self-certification is unresolved, do not fabricate a decision; route to exception workflow.",
            "Reconciliation Control": "Sample decision trace and compare against manual Compliance decision for high-risk cases.",
            "Evidence Status": DEFAULT_STATUS,
        },
        {
            "Derived Rule": "Account aggregation / high-value flag",
            "Inputs": "Customer/party identifier, linked accounts, product balances, aggregation group, snapshot date",
            "Implementation Logic": "Aggregate relevant accounts belonging to the same account holder where rules require aggregation; flag high-value review threshold where exceeded.",
            "Fallback / Limitation": "If customer-party linkage is incomplete, create data lineage exception and review manually.",
            "Reconciliation Control": "Compare aggregated balances to account-level totals and relationship manager high-value population.",
            "Evidence Status": DEFAULT_STATUS,
        },
        {
            "Derived Rule": "Currency conversion",
            "Inputs": "Original amount, original currency, reporting currency, FX rate source, conversion date",
            "Implementation Logic": "Convert amounts only where reporting schema requires it; store original amount, currency, rate source and rate date.",
            "Fallback / Limitation": "If official FX source is not confirmed, create verification task before hard-coding rate source.",
            "Reconciliation Control": "Recalculate sample conversions independently and tie FX source to approved market/reference-data feed.",
            "Evidence Status": DEFAULT_STATUS,
        },
        {
            "Derived Rule": "Passive NFE look-through",
            "Inputs": "Entity classification, passive income/asset indicators, controlling-person records, ownership/control evidence",
            "Implementation Logic": "Where entity is Passive NFE, derive reportability from controlling-person tax residence and include required controlling-person fields.",
            "Fallback / Limitation": "If controlling-person population is missing, block final classification and open remediation case.",
            "Reconciliation Control": "Passive NFE count reconciles to KYC entity population and beneficial ownership records.",
            "Evidence Status": DEFAULT_STATUS,
        },
        {
            "Derived Rule": "Gross income aggregation",
            "Inputs": "Interest events, dividend events, redemption/sale events, account reference, payment dates, reversal markers",
            "Implementation Logic": "Aggregate relevant payments by account, payment type and reporting year; preserve event-level drill-down for QA.",
            "Fallback / Limitation": "Do not substitute GL totals for account-level income unless allocation lineage is approved.",
            "Reconciliation Control": "Payment totals reconcile to custody/product ledger and finance sign-off pack.",
            "Evidence Status": DEFAULT_STATUS,
        },
    ]


def _exception_rows() -> list[dict[str, str]]:
    return [
        {
            "Exception": "Missing TIN",
            "Detection Rule": "TIN is blank where account holder jurisdiction and local rules require it, or missing reason is not captured.",
            "Impact": "May create schema rejection, incomplete CRS record or reportable undocumented population.",
            "Required Action": "Open remediation/outreach case, document reasonable efforts, apply verified local missing-TIN treatment only after Compliance approval.",
            "Owner / SLA": "Compliance Operations / before filing cut-off",
            "Evidence to Retain": "Outreach records, customer response, approval, unresolved exception report",
            "Evidence Status": DEFAULT_STATUS,
        },
        {
            "Exception": "Invalid TIN format",
            "Detection Rule": "TIN fails jurisdiction-specific format, checksum or character validation where configured.",
            "Impact": "Potential portal/schema rejection or inaccurate report.",
            "Required Action": "Route to remediation; do not overwrite with placeholder or padded value unless official guidance supports it.",
            "Owner / SLA": "KYC / before XML creation",
            "Evidence to Retain": "Validation report, corrected value source, approval history",
            "Evidence Status": DEFAULT_STATUS,
        },
        {
            "Exception": "Missing or unreliable self-certification",
            "Detection Rule": "Self-certification missing, expired by verified local rule, inconsistent with KYC indicia or not signed/dated.",
            "Impact": "Reportability decision may be unsupported.",
            "Required Action": "Trigger self-certification cure workflow and Compliance review; record reasonableness assessment.",
            "Owner / SLA": "KYC Operations / policy-defined cure window",
            "Evidence to Retain": "Self-cert copy/status, contact attempts, reasonableness check, escalation log",
            "Evidence Status": DEFAULT_STATUS,
        },
        {
            "Exception": "Passive NFE without controlling persons",
            "Detection Rule": "Entity classification is Passive NFE but zero controlling persons are linked or tax data is incomplete.",
            "Impact": "Look-through reporting cannot be completed.",
            "Required Action": "Open entity remediation case and block final classification until controlling-person records are complete or approved exception exists.",
            "Owner / SLA": "Entity KYC / before reportability sign-off",
            "Evidence to Retain": "Beneficial ownership evidence, outreach records, Compliance approval",
            "Evidence Status": DEFAULT_STATUS,
        },
        {
            "Exception": "Contradictory tax residence indicators",
            "Detection Rule": "Self-certified tax residence conflicts with residence address, mailing address, phone, RM knowledge or documentary evidence.",
            "Impact": "Self-certification reasonableness is questionable.",
            "Required Action": "Create reasonableness exception and request clarification or documentary evidence.",
            "Owner / SLA": "Compliance / KYC / before filing sign-off",
            "Evidence to Retain": "Indicia report, review decision, customer clarification, approval trail",
            "Evidence Status": DEFAULT_STATUS,
        },
        {
            "Exception": "Unsupported characters / transliteration issue",
            "Detection Rule": "Name/address contains characters not accepted by local schema or portal validation.",
            "Impact": "XML submission may reject or corrupt customer data.",
            "Required Action": "Apply documented transliteration rule; retain original value and transformed value.",
            "Owner / SLA": "Technology / before XML generation",
            "Evidence to Retain": "Transformation log and sample validation output",
            "Evidence Status": DEFAULT_STATUS,
        },
        {
            "Exception": "Balance or income reconciliation break",
            "Detection Rule": "Account-level CRS totals do not reconcile to finance/product control totals within tolerance.",
            "Impact": "Incomplete or inaccurate financial reporting.",
            "Required Action": "Investigate source feed gap, event exclusions and currency conversion before file approval.",
            "Owner / SLA": "Finance Data Owner / before Compliance sign-off",
            "Evidence to Retain": "Reconciliation pack, variance explanation, sign-off",
            "Evidence Status": DEFAULT_STATUS,
        },
        {
            "Exception": "Duplicate account or DocRefId",
            "Detection Rule": "Same account/reporting period appears more than once or DocRefId is reused incorrectly.",
            "Impact": "Duplicate reporting or correction/rejection issues.",
            "Required Action": "Deduplicate using account key/reporting year and enforce unique DocRefId generation.",
            "Owner / SLA": "Technology / before submission",
            "Evidence to Retain": "Duplicate report, correction decision, ID generation log",
            "Evidence Status": DEFAULT_STATUS,
        },
    ]


def _control_rows() -> list[dict[str, str]]:
    return [
        {
            "Control ID": "CRS-C-001",
            "Objective": "Complete CRS source data before reportability decision",
            "Type": "Preventive",
            "Owner": "Compliance Operations",
            "Frequency": "Daily during reporting cycle; monthly BAU",
            "Evidence": "Open/closed exception report with owner, age, status and approval trail",
            "Failure Escalation": "Compliance Owner if unresolved at filing cut-off",
            "Evidence Status": DEFAULT_STATUS,
        },
        {
            "Control ID": "CRS-C-002",
            "Objective": "TIN values are present and valid where required",
            "Type": "Preventive / Detective",
            "Owner": "KYC Data Owner",
            "Frequency": "At onboarding and pre-filing",
            "Evidence": "TIN validation report, remediation case log, local rule reference",
            "Failure Escalation": "Tax/Legal review for unresolved missing-TIN population",
            "Evidence Status": DEFAULT_STATUS,
        },
        {
            "Control ID": "CRS-C-003",
            "Objective": "Reportability engine produces reproducible decisions",
            "Type": "Detective",
            "Owner": "Technology + Compliance QA",
            "Frequency": "Each reporting run",
            "Evidence": "Decision trace with input snapshot, rule version, output and timestamp",
            "Failure Escalation": "Block file creation until failed rules are remediated or approved",
            "Evidence Status": DEFAULT_STATUS,
        },
        {
            "Control ID": "CRS-C-004",
            "Objective": "Financial amounts reconcile to authoritative source/control totals",
            "Type": "Detective",
            "Owner": "Finance Data Owner",
            "Frequency": "Each draft and final reporting run",
            "Evidence": "Balance/income reconciliation pack and sign-off",
            "Failure Escalation": "Finance + Compliance sign-off required for material variance",
            "Evidence Status": DEFAULT_STATUS,
        },
        {
            "Control ID": "CRS-C-005",
            "Objective": "FATCA indicators do not contaminate CRS-only rules",
            "Type": "Preventive",
            "Owner": "Compliance Rule Owner",
            "Frequency": "Rule change and UAT",
            "Evidence": "Rule inventory showing CRS vs FATCA inputs and separate test cases",
            "Failure Escalation": "Compliance architecture review before release",
            "Evidence Status": DEFAULT_STATUS,
        },
        {
            "Control ID": "CRS-C-006",
            "Objective": "Manual overrides are approved and traceable",
            "Type": "Preventive",
            "Owner": "Operations Manager",
            "Frequency": "Every override",
            "Evidence": "Maker-checker approval, reason code, evidence link and change log",
            "Failure Escalation": "Remove override from production file if evidence is incomplete",
            "Evidence Status": DEFAULT_STATUS,
        },
    ]


def _test_rows() -> list[dict[str, str]]:
    return [
        {
            "Scenario ID": "UAT-001",
            "Scenario": "New individual account with foreign tax residence and valid TIN",
            "Input Data": "Individual, valid self-certification, foreign ResCountryCode, valid TIN, year-end balance",
            "Expected Processing": "Reportability flag true; XML contains name, address, tax residence, TIN and account balance.",
            "Acceptance Criteria": "Decision trace shows rule version and no open exceptions.",
            "Related Control": "CRS-C-003",
            "Evidence Status": DEFAULT_STATUS,
        },
        {
            "Scenario ID": "UAT-002",
            "Scenario": "Reportable account with missing TIN",
            "Input Data": "Foreign tax residence, blank TIN, otherwise complete account data",
            "Expected Processing": "Exception created; local missing-TIN treatment applied only if verified; no fabricated placeholder.",
            "Acceptance Criteria": "Exception report, remediation status and Compliance decision are captured.",
            "Related Control": "CRS-C-002",
            "Evidence Status": DEFAULT_STATUS,
        },
        {
            "Scenario ID": "UAT-003",
            "Scenario": "Passive NFE with reportable controlling person",
            "Input Data": "Entity classified Passive NFE, controlling person tax resident abroad, valid CP TIN, balance above threshold where applicable",
            "Expected Processing": "Account report includes entity and controlling-person details; reportable flag true.",
            "Acceptance Criteria": "Look-through rule and controlling-person extraction are evidenced.",
            "Related Control": "CRS-C-003",
            "Evidence Status": DEFAULT_STATUS,
        },
        {
            "Scenario ID": "UAT-004",
            "Scenario": "Passive NFE with no controlling persons captured",
            "Input Data": "Entity classified Passive NFE, zero controlling persons in KYC extract",
            "Expected Processing": "Exception raised; final classification blocked pending remediation or approved exception.",
            "Acceptance Criteria": "No silent suppression; remediation case exists.",
            "Related Control": "CRS-C-001",
            "Evidence Status": DEFAULT_STATUS,
        },
        {
            "Scenario ID": "UAT-005",
            "Scenario": "Contradictory self-certification and address indicia",
            "Input Data": "Self-cert says domestic tax residence; address or phone indicates another jurisdiction",
            "Expected Processing": "Reasonableness exception created and routed to Compliance/KYC review.",
            "Acceptance Criteria": "Customer clarification or Compliance approval retained.",
            "Related Control": "CRS-C-001",
            "Evidence Status": DEFAULT_STATUS,
        },
        {
            "Scenario ID": "UAT-006",
            "Scenario": "Closed account during reporting year",
            "Input Data": "Account closed before year-end, closure date present, reportable account holder",
            "Expected Processing": "Closed-account reporting treatment follows verified jurisdiction/schema rule; balance handling is traceable.",
            "Acceptance Criteria": "Closure status, date, balance and local rule reference are present.",
            "Related Control": "CRS-C-003",
            "Evidence Status": DEFAULT_STATUS,
        },
        {
            "Scenario ID": "UAT-007",
            "Scenario": "Income reconciliation variance",
            "Input Data": "CRS income extract differs from product ledger/GL control total",
            "Expected Processing": "File approval blocked or variance approved according to materiality threshold.",
            "Acceptance Criteria": "Variance report, root cause and sign-off retained.",
            "Related Control": "CRS-C-004",
            "Evidence Status": DEFAULT_STATUS,
        },
        {
            "Scenario ID": "UAT-008",
            "Scenario": "FATCA enabled but CRS rule excludes US-only indicia",
            "Input Data": "US place of birth or US phone present with FATCA toggle enabled",
            "Expected Processing": "US indicia appear only in FATCA crosswalk; CRS reportability remains based on CRS tax residence logic.",
            "Acceptance Criteria": "Separate CRS and FATCA decision traces exist.",
            "Related Control": "CRS-C-005",
            "Evidence Status": DEFAULT_STATUS,
        },
    ]


def _backlog_rows() -> list[dict[str, str]]:
    return [
        {
            "Backlog Item": "Build CRS source-data extract",
            "Build Requirement": "Create repeatable extract for customer, account, balance, income, self-certification, TIN and controlling-person data with lineage to source systems.",
            "Acceptance Criteria": "Extract contains required fields, source timestamp, record counts and reconciliation totals; failed rows go to exception register.",
            "Owner": "Technology / Data Engineering",
            "Evidence Status": DEFAULT_STATUS,
        },
        {
            "Backlog Item": "Build reportability decision engine",
            "Build Requirement": "Implement deterministic CRS decision rules with stored reason codes and input snapshots.",
            "Acceptance Criteria": "Every output record includes decision result, reason code, rule version and evidence link; UAT scenarios pass.",
            "Owner": "Technology / Compliance Rule Owner",
            "Evidence Status": DEFAULT_STATUS,
        },
        {
            "Backlog Item": "Build exception workflow",
            "Build Requirement": "Route missing/invalid CRS data to named owners with SLA, status, remediation evidence and approval workflow.",
            "Acceptance Criteria": "Unresolved mandatory exceptions block final file unless Compliance override is recorded.",
            "Owner": "Operations / Compliance",
            "Evidence Status": DEFAULT_STATUS,
        },
        {
            "Backlog Item": "Build XML generation and validation pack",
            "Build Requirement": "Generate CRS XML from approved reportable population and validate against schema/local portal rules where available.",
            "Acceptance Criteria": "XML validates, DocRefId uniqueness enforced, rejection handling workflow tested.",
            "Owner": "Technology",
            "Evidence Status": DEFAULT_STATUS,
        },
    ]


def _operations_runbook_rows() -> list[dict[str, str]]:
    return [
        {
            "Runbook Step": "Pre-cycle source readiness",
            "Action": "Confirm source systems, extract owners, reporting calendar, rule version and jurisdiction verification tasks.",
            "Primary Owner": "Compliance Owner",
            "Evidence": "Readiness checklist and source-owner sign-off",
            "Evidence Status": DEFAULT_STATUS,
        },
        {
            "Runbook Step": "Daily/weekly exception review",
            "Action": "Review missing TIN, self-certification, tax residence, controlling-person and reconciliation exceptions until closure.",
            "Primary Owner": "Operations",
            "Evidence": "Aged exception report and remediation notes",
            "Evidence Status": DEFAULT_STATUS,
        },
        {
            "Runbook Step": "Pre-filing QA sign-off",
            "Action": "Approve reportable population, reconciliation pack, UAT evidence, unresolved exceptions and local verification tasks.",
            "Primary Owner": "Compliance + Finance + Technology",
            "Evidence": "Signed QA pack and approval block",
            "Evidence Status": DEFAULT_STATUS,
        },
        {
            "Runbook Step": "Post-submission handling",
            "Action": "Track portal acknowledgement/rejections, correction files, voids and regulator correspondence.",
            "Primary Owner": "Compliance Operations",
            "Evidence": "Submission receipt, rejection log, correction register",
            "Evidence Status": DEFAULT_STATUS,
        },
    ]


def _verification_rows(params: dict, kb: dict) -> list[dict[str, str]]:
    jurisdiction = safe_text(params.get("jurisdiction") or kb.get("country") or "Selected jurisdiction")
    source_registry = kb.get("_source_registry", {}) if isinstance(kb.get("_source_registry"), dict) else {}
    local_url = source_registry.get("local_url") or (kb.get("contact") or {}).get("website") or "Registered local authority CRS/FATCA page"
    authority = safe_text(kb.get("authority") or source_registry.get("authority") or "Competent authority not captured")
    deadline = safe_text(kb.get("reporting_deadline") or "Not captured in curated KB")
    portal = safe_text(kb.get("portal_name") or kb.get("portal_url") or "Not captured in curated KB")
    nil_report = safe_text(kb.get("nil_report_required") or "Not captured in curated KB")
    schema = safe_text(kb.get("xml_schema") or kb.get("xml_schema_version") or "Not captured in curated KB")
    rows = [
        {
            "Verification Task": f"Confirm competent authority for {jurisdiction}",
            "Current Signal": authority,
            "Simple Message": "Check this is still the authority that receives or supervises CRS reporting for the selected reporting year.",
            "Where To Check": local_url,
            "Evidence To Retain": "Official page/PDF, URL, access date and reviewer sign-off.",
            "Technology Guardrail": "Do not hard-code authority/recipient routing until source is confirmed for the reporting year.",
            "Evidence Status": _status_from_kb(kb.get("authority")),
        },
        {
            "Verification Task": f"Confirm CRS filing deadline for {jurisdiction}",
            "Current Signal": deadline,
            "Simple Message": "Confirm the exact due date before setting the reporting calendar, remediation cut-off or submission workflow.",
            "Where To Check": local_url,
            "Evidence To Retain": "Deadline guidance, screenshot/PDF, reporting year and sign-off.",
            "Technology Guardrail": "Store the deadline as a configurable parameter, not embedded code.",
            "Evidence Status": _status_from_kb(kb.get("reporting_deadline")),
        },
        {
            "Verification Task": "Confirm submission portal, upload method and rejection handling",
            "Current Signal": portal,
            "Simple Message": "Check the exact portal, file upload method, schema validation and rejection-code process before UAT.",
            "Where To Check": local_url,
            "Evidence To Retain": "Portal guidance, validation guide, rejection-code examples and access evidence.",
            "Technology Guardrail": "Build portal endpoint/schema validation as configurable; do not rely on inferred portal names.",
            "Evidence Status": _status_from_kb(kb.get("portal_url") or kb.get("portal_name")),
        },
        {
            "Verification Task": "Confirm nil-reporting treatment",
            "Current Signal": nil_report,
            "Simple Message": "Check whether a nil declaration is required when there are no reportable accounts.",
            "Where To Check": local_url,
            "Evidence To Retain": "Nil-reporting rule extract and operations sign-off.",
            "Technology Guardrail": "Configure zero-reportable-account workflow separately from normal report generation.",
            "Evidence Status": _status_from_kb(kb.get("nil_report_required")),
        },
        {
            "Verification Task": "Confirm schema version and local technical specification",
            "Current Signal": schema,
            "Simple Message": "Check the exact CRS XML schema/version and local validation rules before building the generator.",
            "Where To Check": local_url,
            "Evidence To Retain": "Technical specification, XSD version, validation samples and approval record.",
            "Technology Guardrail": "Version the XML generator and retain schema validation logs for each production file.",
            "Evidence Status": _status_from_kb(kb.get("xml_schema") or kb.get("xml_schema_version")),
        },
        {
            "Verification Task": "Confirm client physical source-field mapping",
            "Current Signal": "Logical system and alias guidance generated; client-specific table/column names not supplied",
            "Simple Message": "Ask Technology/Data Owners to map each logical CRS field to the actual extract, table, column or API attribute before build.",
            "Where To Check": "Client data dictionary, source-system interface specification, vendor extract configuration and sample data profiling output",
            "Evidence To Retain": "Approved source-to-target mapping, data lineage, sample extract, owner sign-off and unresolved mapping gaps.",
            "Technology Guardrail": "Do not treat vendor-aware aliases in this blueprint as physical field names; they are implementation hints only.",
            "Evidence Status": LOCAL_STATUS,
        },
    ]
    overlay = _load_overlay(params, kb)
    for key, label in [("tin", "Confirm TIN format and missing-TIN treatment"), ("nil_reporting", "Confirm nil/no-reportable-account treatment"), ("self_certification", "Confirm self-certification cure and reliability rules")]:
        item = overlay.get(key, {}) if isinstance(overlay.get(key), dict) else {}
        if item:
            rows.append({
                "Verification Task": safe_text(item.get("verification_task") or label),
                "Current Signal": safe_text(item.get("local_label") or item.get("state") or item.get("validity_rule") or "Overlay guidance available"),
                "Simple Message": safe_text(item.get("verification_task") or label),
                "Where To Check": safe_text(item.get("source_url") or local_url),
                "Evidence To Retain": "Official guidance/PDF, URL, access date, reviewer sign-off and configuration decision.",
                "Technology Guardrail": "Keep validation, workflow and reason-code treatment configurable until the check is completed.",
                "Evidence Status": safe_text(item.get("evidence_status") or LOCAL_STATUS),
            })
    return rows


def _how_to_read_blocks() -> list[dict[str, Any]]:
    return [
        {
            "type": "table",
            "title": "How to read this blueprint - evidence legend",
            "columns": ["Label", "Meaning", "How to use it", "Evidence Status"],
            "rows": [
                {"Label": "Verified", "Meaning": "Supported by curated CRS knowledge, deterministic CRS logic, selected user inputs or registered source metadata.", "How to use it": "Can be used as a build baseline, subject to normal sign-off.", "Evidence Status": DEFAULT_STATUS},
                {"Label": "User input", "Meaning": "Comes directly from the jurisdiction, FI type, systems, year or options selected by the user.", "How to use it": "Confirm it reflects the intended reporting entity and scope.", "Evidence Status": USER_STATUS},
                {"Label": "Needs verification", "Meaning": "A practical check is required before build lock, filing configuration or production use.", "How to use it": "Follow the verification task: check source, retain evidence and avoid hard-coding until signed off.", "Evidence Status": LOCAL_STATUS},
                {"Label": "Implementation hint", "Meaning": "Useful generic CRS or system guidance, not a confirmed client-specific physical mapping.", "How to use it": "Use as a starting point for workshops and source-to-target mapping.", "Evidence Status": "Implementation hint"},
            ],
            "evidence_status": DEFAULT_STATUS,
        },
        {
            "type": "table",
            "title": "How to read this blueprint - source layer legend",
            "columns": ["Source Layer", "Meaning", "Implementation Use", "Evidence Status"],
            "rows": [
                {"Source Layer": "Global CRS baseline", "Meaning": "Common CRS implementation requirement shared across jurisdictions.", "Implementation Use": "Build consistently across countries unless a local overlay overrides it.", "Evidence Status": DEFAULT_STATUS},
                {"Source Layer": "Institution-type overlay", "Meaning": "Requirement varies by Depository, Custodial, Investment Entity or Insurance classification.", "Implementation Use": "Use to scope product/account populations and responsibility owners.", "Evidence Status": DEFAULT_STATUS},
                {"Source Layer": "Jurisdiction overlay", "Meaning": "Rule or instruction is specific to the selected reporting jurisdiction.", "Implementation Use": "Prioritise these rows for local compliance review and configuration.", "Evidence Status": LOCAL_STATUS},
                {"Source Layer": "System overlay", "Meaning": "Guidance depends on selected upstream systems or platforms.", "Implementation Use": "Validate against the client data dictionary and interface specs.", "Evidence Status": "Implementation hint"},
                {"Source Layer": "User-document overlay", "Meaning": "Instruction came from an uploaded requirements/policy document.", "Implementation Use": "Trace to the uploaded source and resolve conflicts with official guidance.", "Evidence Status": USER_STATUS},
            ],
            "evidence_status": DEFAULT_STATUS,
        },
    ]


def _material_difference_rows(params: dict, kb: dict) -> list[dict[str, str]]:
    overlay = _load_overlay(params, kb)
    rows: list[dict[str, str]] = []
    for item in overlay.get("material_differences", []) if isinstance(overlay.get("material_differences"), list) else []:
        if isinstance(item, dict):
            rows.append({
                "Area": safe_text(item.get("Area") or item.get("area")),
                "What changes in this jurisdiction": safe_text(item.get("What Changes") or item.get("what_changes") or item.get("What changes")),
                "Implementation impact": safe_text(item.get("Implementation Impact") or item.get("implementation_impact")),
                "Verification task": safe_text(item.get("Verification Task") or item.get("verification_task")),
                "Source Layer": "Jurisdiction overlay",
                "Evidence Status": safe_text(item.get("Evidence Status") or item.get("evidence_status") or LOCAL_STATUS),
            })
    if rows:
        return rows
    return [
        {"Area": "Local filing configuration", "What changes in this jurisdiction": "Jurisdiction-specific portal, deadline, schema and nil-reporting treatment are not fully captured in an implementation overlay yet.", "Implementation impact": "Keep these settings configurable and do not reuse another jurisdiction’s route or calendar without review.", "Verification task": "Confirm authority guidance, deadline, submission route and schema before build lock.", "Source Layer": "Jurisdiction overlay", "Evidence Status": LOCAL_STATUS}
    ]


def _tin_guidance_rows(params: dict, kb: dict) -> list[dict[str, str]]:
    overlay = _load_overlay(params, kb)
    tin = overlay.get("tin", {}) if isinstance(overlay.get("tin"), dict) else {}
    jurisdiction = safe_text(params.get("jurisdiction") or kb.get("country") or overlay.get("jurisdiction") or "Selected jurisdiction")
    if not tin:
        return [{
            "Requirement Area": "TIN/local identifier configuration",
            "Jurisdiction-Specific Guidance": "No detailed TIN overlay is available for this jurisdiction yet.",
            "Technology Build Instruction": "Keep TIN format, missing-reason and default treatment configurable by jurisdiction.",
            "Verification / Evidence Required": "Confirm local TIN format, missing-TIN treatment and permitted reason codes before UAT.",
            "Source Layer": "Global CRS baseline + Jurisdiction overlay",
            "Evidence Status": LOCAL_STATUS,
        }]
    label = safe_text(tin.get("local_label") or "TIN / local tax identifier")
    fmt = safe_text(tin.get("format") or tin.get("regex") or "Format not confirmed")
    examples = ", ".join(safe_text(x) for x in tin.get("valid_examples", []) if safe_text(x)) or "Examples not captured"
    default_allowed = "Yes" if tin.get("default_allowed") is True else "No"
    reason_codes = ", ".join(safe_text(x) for x in tin.get("permitted_missing_reason_codes", []) if safe_text(x)) or "None captured / not assumed"
    return [
        {
            "Requirement Area": "Local identifier label and applicability",
            "Jurisdiction-Specific Guidance": f"For {jurisdiction}, use {label}. {safe_text(tin.get('applicability') or 'Apply the local TIN rule when the account holder or controlling person is tax resident in this jurisdiction.')}",
            "Technology Build Instruction": "Store local identifier label and account-holder applicability in jurisdiction reference data; do not hard-code a global label.",
            "Verification / Evidence Required": safe_text(tin.get("verification_task") or "Confirm accepted local TIN labels and applicability before build lock."),
            "Source Layer": "Global CRS baseline + Jurisdiction overlay",
            "Evidence Status": safe_text(tin.get("evidence_status") or LOCAL_STATUS),
        },
        {
            "Requirement Area": "Format and validation",
            "Jurisdiction-Specific Guidance": f"Expected format hint: {fmt}. Example values: {examples}.",
            "Technology Build Instruction": "Configure format/regex/checksum validation as jurisdiction reference data and version the rule used for each reporting year.",
            "Verification / Evidence Required": safe_text(tin.get("validation_rule") or "Confirm official format and any checksum before production validation."),
            "Source Layer": "Jurisdiction overlay",
            "Evidence Status": safe_text(tin.get("evidence_status") or LOCAL_STATUS),
        },
        {
            "Requirement Area": "Default and placeholder treatment",
            "Jurisdiction-Specific Guidance": f"Default or placeholder TIN allowed by this overlay: {default_allowed}. Permitted missing reason codes: {reason_codes}.",
            "Technology Build Instruction": "Block dummy values such as Unknown, 000000, padded identifiers or free-text notes unless official guidance explicitly permits a reason code.",
            "Verification / Evidence Required": "Retain official guidance and Compliance/Tax sign-off for any permitted missing reason code or placeholder treatment.",
            "Source Layer": "Jurisdiction overlay",
            "Evidence Status": safe_text(tin.get("evidence_status") or LOCAL_STATUS),
        },
        {
            "Requirement Area": "Missing or invalid TIN remediation",
            "Jurisdiction-Specific Guidance": safe_text(tin.get("missing_data_action") or "Open remediation and document reasonable efforts; do not fabricate values."),
            "Technology Build Instruction": "Create missing/invalid TIN exceptions with owner, SLA, customer outreach evidence, approval status and reporting-treatment decision.",
            "Verification / Evidence Required": "Retain outreach attempts, customer response, validation result, unresolved population report and Compliance approval.",
            "Source Layer": "Global CRS baseline + Jurisdiction overlay + System overlay",
            "Evidence Status": safe_text(tin.get("evidence_status") or LOCAL_STATUS),
        },
    ]


def _jurisdiction_quick_check_rows(params: dict, kb: dict) -> list[dict[str, str]]:
    overlay = _load_overlay(params, kb)
    tin = overlay.get("tin", {}) if isinstance(overlay.get("tin"), dict) else {}
    nilr = overlay.get("nil_reporting", {}) if isinstance(overlay.get("nil_reporting"), dict) else {}
    selfc = overlay.get("self_certification", {}) if isinstance(overlay.get("self_certification"), dict) else {}
    return [
        {"Check": "TIN/local identifier", "Current Signal": safe_text(tin.get("local_label") or "Not captured"), "What To Do Before Build Lock": safe_text(tin.get("verification_task") or "Confirm local format, missing-TIN treatment and reason codes."), "Evidence Status": safe_text(tin.get("evidence_status") or LOCAL_STATUS)},
        {"Check": "Nil/no-reportable-account treatment", "Current Signal": safe_text(nilr.get("state") or "Not captured"), "What To Do Before Build Lock": safe_text(nilr.get("verification_task") or "Confirm zero-reportable-account workflow."), "Evidence Status": safe_text(nilr.get("evidence_status") or LOCAL_STATUS)},
        {"Check": "Self-certification reliability", "Current Signal": safe_text(selfc.get("refresh_requirement") or selfc.get("validity_rule") or "Not captured"), "What To Do Before Build Lock": safe_text(selfc.get("verification_task") or "Confirm cure/reliability treatment and workflow SLA."), "Evidence Status": safe_text(selfc.get("evidence_status") or LOCAL_STATUS)},
    ]

def _source_health_rows(kb: dict, params: dict | None = None) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    registry = _load_source_registry(params or {}, kb)
    summary = freshness_from_registry(registry)
    sources = []
    for src in registry.get("sources", []) if isinstance(registry.get("sources"), list) else []:
        if isinstance(src, dict):
            sources.append({
                "Source": src.get("source_title") or src.get("authority") or src.get("source_id") or "Registered official source",
                "URL / Location": src.get("url", ""),
                "Expected Use": ", ".join(src.get("facts_expected", [])) if isinstance(src.get("facts_expected"), list) else src.get("expected_use", "Official fact support"),
                "Refresh / Source Status": src.get("source_freshness") or summary["status"],
                "Last Verified": src.get("last_verified") or summary["last_verified"],
                "Check Logic": src.get("check_logic", "Use only registered official/authority domains; if unavailable or changed, create a verification task instead of inventing the fact."),
                "Evidence Status": src.get("evidence_status", DEFAULT_STATUS),
            })
    if registry.get("local_url") and not any(s.get("URL / Location") == registry.get("local_url") for s in sources):
        sources.append({
            "Source": "Local authority CRS guidance",
            "URL / Location": registry["local_url"],
            "Expected Use": "Authority, deadline, portal, nil reporting, local schema",
            "Refresh / Source Status": summary["status"],
            "Last Verified": summary["last_verified"],
        })
    if registry.get("oecd_url") and not any(s.get("URL / Location") == registry.get("oecd_url") for s in sources):
        sources.append({
            "Source": "OECD CRS jurisdiction page",
            "URL / Location": registry["oecd_url"],
            "Expected Use": "CRS participation/status and exchange context",
            "Refresh / Source Status": summary["status"],
            "Last Verified": summary["last_verified"],
        })
    for meta in kb.get("_meta", {}).get("sources", []) if isinstance(kb.get("_meta"), dict) else []:
        if isinstance(meta, dict):
            sources.append({
                "Source": meta.get("notes", "Curated KB source"),
                "URL / Location": meta.get("url", ""),
                "Expected Use": "Curated jurisdiction fact support",
                "Refresh / Source Status": summary["status"],
                "Last Verified": meta.get("fetched_at") or summary["last_verified"],
            })
    if not sources:
        sources = [{
            "Source": "Curated KB source registry",
            "URL / Location": "Not configured",
            "Expected Use": "Add official source before marking jurisdiction facts verified",
            "Refresh / Source Status": "Not checked",
            "Last Verified": "Not recorded",
        }]

    rows.append({
        "Source": "KB refresh model",
        "URL / Location": "Registered official sources only",
        "Expected Use": "Runtime generation uses curated KB facts and does not rewrite compliance facts from live webpages.",
        "Refresh / Source Status": summary["status"],
        "Last Verified": summary["last_verified"],
        "Check Logic": summary["refresh_frequency"] + "; source changes become review tasks, not silent fact updates.",
        "Evidence Status": DEFAULT_STATUS if summary["status"] != "Not checked" else LOCAL_STATUS,
    })

    for source in sources[:6]:
        rows.append({
            "Source": safe_text(source.get("Source")),
            "URL / Location": safe_text(source.get("URL / Location")),
            "Expected Use": safe_text(source.get("Expected Use")),
            "Refresh / Source Status": safe_text(source.get("Refresh / Source Status") or summary["status"]),
            "Last Verified": safe_text(source.get("Last Verified") or summary["last_verified"]),
            "Check Logic": safe_text(source.get("Check Logic") or "Use only registered official/authority domains; if unavailable or changed, create a verification task instead of inventing the fact."),
            "Evidence Status": safe_text(source.get("Evidence Status") or (DEFAULT_STATUS if source.get("URL / Location") and source.get("URL / Location") != "Not configured" else LOCAL_STATUS)),
        })
    return rows

def _implementation_completeness_rows(structured: dict) -> list[dict[str, str]]:
    sections = structured.get("sections", {})
    field_rows = len(_field_catalog_rows({}, {}))
    derived_rows = len(_derived_rule_rows({}))
    exception_rows = len(_exception_rows())
    control_rows = len(_control_rows())
    test_rows = len(_test_rows())
    return [
        {"Dimension": "Field catalogue", "Generated Items": str(field_rows), "What This Proves": "Required CRS data elements have source, validation and missing-data actions.", "Evidence Status": DEFAULT_STATUS},
        {"Dimension": "Transformation rules", "Generated Items": str(derived_rows), "What This Proves": "Technology has rules for reportability, aggregation, income and currency conversion.", "Evidence Status": DEFAULT_STATUS},
        {"Dimension": "Exception handling", "Generated Items": str(exception_rows), "What This Proves": "Operations has concrete treatment for missing or invalid data.", "Evidence Status": DEFAULT_STATUS},
        {"Dimension": "Controls", "Generated Items": str(control_rows), "What This Proves": "Compliance can evidence completeness, validity and sign-off.", "Evidence Status": DEFAULT_STATUS},
        {"Dimension": "UAT scenarios", "Generated Items": str(test_rows), "What This Proves": "QA can prove positive, negative and edge-case processing.", "Evidence Status": DEFAULT_STATUS},
        {"Dimension": "Jurisdiction-specific items", "Generated Items": str(sum(1 for sec in sections.values() for b in sec.get("blocks", []) for r in b.get("rows", []) if "Jurisdiction overlay" in str(r))), "What This Proves": "Local overlay items are visible separately from the global CRS baseline.", "Evidence Status": DEFAULT_STATUS},
    ]


def _downstream_rows(kb: dict) -> list[dict[str, str]]:
    authority = safe_text(kb.get("authority") or "Competent authority to be verified")
    deadline = safe_text(kb.get("reporting_deadline") or "Not confirmed")
    schema = safe_text(kb.get("xml_schema") or kb.get("xml_schema_version") or "Schema/version not confirmed")
    portal = safe_text(kb.get("portal_name") or kb.get("portal_url") or "Portal not confirmed")
    return [
        {
            "Build Area": "Reporting calendar configuration",
            "Requirement": "Configure reporting period, snapshot date, remediation cut-off, QA sign-off date and filing deadline as reference data.",
            "Current Signal": deadline,
            "Technology Instruction": "Do not hard-code dates; create reporting-year parameter table and approval workflow.",
            "Evidence / Control": "Calendar sign-off, date source evidence, deployment record",
            "Evidence Status": _status_from_kb(kb.get("reporting_deadline")),
        },
        {
            "Build Area": "XML/schema generation",
            "Requirement": "Generate CRS XML from approved reportable population and validate against the applicable local/OECD schema.",
            "Current Signal": schema,
            "Technology Instruction": "Version the XML generator by schema version; retain validation logs for draft and final files.",
            "Evidence / Control": "XSD validation output, schema version record, sample XML pack",
            "Evidence Status": _status_from_kb(kb.get("xml_schema") or kb.get("xml_schema_version")),
        },
        {
            "Build Area": "Submission route",
            "Requirement": "Route final file to the competent authority or intermediary portal according to local guidance.",
            "Current Signal": authority + " / " + portal,
            "Technology Instruction": "Keep portal URL, credentials owner, file transport method and acknowledgement handling configurable.",
            "Evidence / Control": "Portal guidance, access record, submission receipt and acknowledgement",
            "Evidence Status": _status_from_kb(kb.get("portal_url") or kb.get("portal_name")),
        },
        {
            "Build Area": "Correction and void workflow",
            "Requirement": "Support correction, deletion/void and resubmission cases with prior reference linkage and approval.",
            "Current Signal": safe_text(kb.get("doc_ref_id_format") or "DocRefId/CorrDocRefId treatment not fully confirmed"),
            "Technology Instruction": "Store original DocRefId/MessageRefId, correction reason, approver and replacement record before generating correction XML.",
            "Evidence / Control": "Correction register, before/after record, approval and schema validation",
            "Evidence Status": _status_from_kb(kb.get("doc_ref_id_format")),
        },
    ]


def _classification_rows() -> list[dict[str, str]]:
    return [
        {
            "Decision Point": "Individual vs entity",
            "Input Data": "Account holder legal form, customer type, KYC party type and product ownership",
            "Processing Rule": "Route individuals to individual due-diligence path; route entities to FI/NFE classification and look-through logic.",
            "Exception Action": "If party type conflicts across systems, open classification exception and require KYC owner decision.",
            "Evidence to Retain": "KYC classification, source-system party type, reviewer decision",
            "Evidence Status": DEFAULT_STATUS,
        },
        {
            "Decision Point": "Reportable person tax residence",
            "Input Data": "Self-certified tax residence, reasonableness indicators, participating/reportable jurisdiction list",
            "Processing Rule": "Report where tax residence is reportable and account is not excluded; retain reason code for non-reportable outcomes.",
            "Exception Action": "Conflicts or missing tax residence route to self-certification remediation.",
            "Evidence to Retain": "Self-certification, reasonableness check, decision trace",
            "Evidence Status": DEFAULT_STATUS,
        },
        {
            "Decision Point": "Entity FI / Active NFE / Passive NFE",
            "Input Data": "Entity self-certification, regulatory status, business activity, passive income/asset indicators",
            "Processing Rule": "Classify entity; Passive NFE triggers controlling-person look-through and individual reportability evaluation.",
            "Exception Action": "Incomplete entity classification blocks final reportability decision for entity accounts.",
            "Evidence to Retain": "Entity classification evidence, UBO/controlling-person records",
            "Evidence Status": DEFAULT_STATUS,
        },
        {
            "Decision Point": "Self-certification reliability",
            "Input Data": "Self-cert status, signature/date, change-in-circumstances flags, inconsistent indicia",
            "Processing Rule": "Treat self-certification as usable only when complete and reasonable against other KYC information held.",
            "Exception Action": "Unreliable or incomplete self-certification creates remediation task; do not rely on stale values without approval.",
            "Evidence to Retain": "Reliability assessment, customer outreach, approval trail",
            "Evidence Status": DEFAULT_STATUS,
        },
    ]


def _fatca_rows(kb: dict) -> list[dict[str, str]]:
    fatca = kb.get("fatca", {}) if isinstance(kb.get("fatca"), dict) else {}
    iga = safe_text(fatca.get("iga_type") or "FATCA IGA model not confirmed")
    portal = safe_text(fatca.get("portal") or kb.get("portal_name") or "FATCA route not confirmed")
    return [
        {
            "Area": "Reporting route",
            "FATCA Instruction": "Keep FATCA route separate from CRS route even where the same authority or portal infrastructure is used.",
            "Current Signal": iga + " / " + portal,
            "Technology Guardrail": "Separate FATCA schema, population rules, indicators and submission controls from CRS configuration.",
            "Evidence Status": _status_from_kb(fatca.get("iga_type") or fatca.get("portal")),
        },
        {
            "Area": "US indicia handling",
            "FATCA Instruction": "US place of birth, US phone, US address and other US indicia are FATCA indicators and must not be inserted into CRS-only logic.",
            "Current Signal": "FATCA-only decision input",
            "Technology Guardrail": "Maintain separate CRS and FATCA rule inventories and test cases.",
            "Evidence Status": DEFAULT_STATUS,
        },
        {
            "Area": "Dual-reporting controls",
            "FATCA Instruction": "Where CRS and FATCA share data sources, reconcile shared identity fields but generate independent reportability decisions.",
            "Current Signal": "Shared KYC/source data; separate rules",
            "Technology Guardrail": "Store CRS reason code and FATCA reason code separately for each account/customer.",
            "Evidence Status": DEFAULT_STATUS,
        },
    ]


def _drop_empty_generation_placeholders(section: dict) -> None:
    blocks = section.get("blocks", [])
    if len(blocks) <= 1:
        return
    cleaned = []
    for block in blocks:
        title = safe_text(block.get("title", "")).lower()
        text = safe_text(block.get("text", "")).lower()
        if title == "not generated" or "this section was not generated" in text:
            continue
        cleaned.append(block)
    section["blocks"] = cleaned


def _executive_action_blocks(params: dict, kb: dict) -> list[dict[str, Any]]:
    jurisdiction = safe_text(params.get("jurisdiction") or kb.get("country") or "selected jurisdiction")
    fi_type = safe_text(params.get("fi_type") or "selected FI type")
    reporting_year = safe_text(params.get("reporting_year") or "selected reporting year")
    deadline = safe_text(kb.get("reporting_deadline") or "Not confirmed in supplied KB")
    authority = safe_text(kb.get("authority") or "Competent authority not confirmed in supplied KB")
    portal = safe_text(kb.get("portal_name") or kb.get("portal_url") or "Submission portal not confirmed in supplied KB")
    nil_report = safe_text(kb.get("nil_report_required") if kb.get("nil_report_required") is not None else "Not confirmed in supplied KB")
    schema = safe_text(kb.get("xml_schema") or kb.get("xml_schema_version") or "Schema/version not confirmed in supplied KB")
    return [
        {
            "type": "table",
            "title": "Implementation action map",
            "columns": ["Workstream", "What Must Be Built / Done", "Primary Owner", "Proof / Evidence", "Evidence Status"],
            "rows": [
                {
                    "Workstream": "Compliance rules",
                    "What Must Be Built / Done": f"Approve CRS reportability logic for {fi_type} in {jurisdiction} for reporting year {reporting_year}; confirm rule version and unresolved local items before production.",
                    "Primary Owner": "Compliance / Tax",
                    "Proof / Evidence": "Approved rule inventory, decision trace samples, review sign-off and local-source evidence pack.",
                    "Evidence Status": USER_STATUS,
                },
                {
                    "Workstream": "Technology build",
                    "What Must Be Built / Done": "Create source extracts, deterministic reportability engine, exception workflow, XML generation, schema validation and correction/void workflow.",
                    "Primary Owner": "Technology / Data Engineering",
                    "Proof / Evidence": "Source-to-target mapping, extract logs, rule version, XSD validation output, deployment record and runbook.",
                    "Evidence Status": DEFAULT_STATUS,
                },
                {
                    "Workstream": "Operations remediation",
                    "What Must Be Built / Done": "Run missing TIN, self-certification, tax residence, controlling-person and reconciliation exception queues with owners, SLAs and approval evidence.",
                    "Primary Owner": "Operations / KYC / Compliance Operations",
                    "Proof / Evidence": "Aged exception report, outreach evidence, maker-checker approvals and unresolved-population sign-off.",
                    "Evidence Status": DEFAULT_STATUS,
                },
                {
                    "Workstream": "QA and evidence",
                    "What Must Be Built / Done": "Execute positive, negative and edge-case UAT scenarios; retain decision traces and reconciliation packs before filing.",
                    "Primary Owner": "QA / Compliance Testing",
                    "Proof / Evidence": "UAT results, defect log, sample XML, control attestations and filing approval pack.",
                    "Evidence Status": DEFAULT_STATUS,
                },
            ],
            "evidence_status": DEFAULT_STATUS,
        },
        {
            "type": "table",
            "title": "Key implementation decisions to confirm before build lock",
            "columns": ["Decision", "Current Signal", "Why It Matters", "Build Guardrail", "Evidence Status"],
            "rows": [
                {
                    "Decision": "Competent authority / recipient route",
                    "Current Signal": authority,
                    "Why It Matters": "Controls submission recipient, credentials, acknowledgement capture and regulator correspondence process.",
                    "Build Guardrail": "Keep recipient and route configurable until source evidence is approved for the reporting year.",
                    "Evidence Status": _status_from_kb(kb.get("authority")),
                },
                {
                    "Decision": "Reporting deadline and cut-off calendar",
                    "Current Signal": deadline,
                    "Why It Matters": "Drives remediation cut-off, QA window, approval date and final submission workflow.",
                    "Build Guardrail": "Store dates in reporting-calendar reference data; do not hard-code them into extraction or XML logic.",
                    "Evidence Status": _status_from_kb(kb.get("reporting_deadline")),
                },
                {
                    "Decision": "Submission portal and rejection handling",
                    "Current Signal": portal,
                    "Why It Matters": "Determines transport method, file validation, rejection queue and post-submission operations.",
                    "Build Guardrail": "Configure portal endpoint, schema version, credentials owner and acknowledgement handling as reference data.",
                    "Evidence Status": _status_from_kb(kb.get("portal_name") or kb.get("portal_url")),
                },
                {
                    "Decision": "Nil-reporting treatment",
                    "Current Signal": nil_report,
                    "Why It Matters": "Controls whether a zero-reportable-account workflow is required and how operations evidence no-reportable status.",
                    "Build Guardrail": "Build a separate nil-report / no-reportable-account workflow only after the local rule is confirmed.",
                    "Evidence Status": _status_from_kb(kb.get("nil_report_required")),
                },
                {
                    "Decision": "Schema and local technical specification",
                    "Current Signal": schema,
                    "Why It Matters": "Controls XML elements, validation, permitted values, correction rules and rejection logic.",
                    "Build Guardrail": "Version the XML generator by schema/specification and retain validation logs for each run.",
                    "Evidence Status": _status_from_kb(kb.get("xml_schema") or kb.get("xml_schema_version")),
                },
            ],
            "evidence_status": DEFAULT_STATUS,
        },
        {
            "type": "numbered_list",
            "title": "Reportability build logic",
            "items": [
                {"text": "Identify whether the account holder is an individual or entity using the KYC party type and account ownership model.", "evidence_status": DEFAULT_STATUS},
                {"text": "For individuals, evaluate tax residence, self-certification reliability, account exclusion status and reportable-jurisdiction status before setting the reportability flag.", "evidence_status": DEFAULT_STATUS},
                {"text": "For entities, classify FI, Active NFE or Passive NFE; if Passive NFE, perform controlling-person look-through and evaluate each controlling person as an individual.", "evidence_status": DEFAULT_STATUS},
                {"text": "Store the decision result, reason code, input snapshot, rule version and exception status for every account/customer evaluated.", "evidence_status": DEFAULT_STATUS},
            ],
            "evidence_status": DEFAULT_STATUS,
        },
    ]


def _raci_rows() -> list[dict[str, str]]:
    return [
        {"Activity": "Rule interpretation and implementation sign-off", "Responsible": "Compliance / Tax", "Accountable": "Compliance Owner", "Consulted": "Legal, Technology", "Informed": "Operations, QA", "Evidence Status": DEFAULT_STATUS},
        {"Activity": "Source-to-target mapping and extract build", "Responsible": "Technology / Data Engineering", "Accountable": "Technology Owner", "Consulted": "Data Owners, Compliance", "Informed": "Operations", "Evidence Status": DEFAULT_STATUS},
        {"Activity": "TIN, self-certification and KYC remediation", "Responsible": "KYC / Operations", "Accountable": "Operations Manager", "Consulted": "Compliance, Relationship Management", "Informed": "Technology", "Evidence Status": DEFAULT_STATUS},
        {"Activity": "Financial amount reconciliation", "Responsible": "Finance Data Owner", "Accountable": "Finance Controller", "Consulted": "Technology, Product Owners", "Informed": "Compliance", "Evidence Status": DEFAULT_STATUS},
        {"Activity": "UAT and production readiness", "Responsible": "QA / Compliance Testing", "Accountable": "Programme Owner", "Consulted": "Technology, Operations", "Informed": "Senior Management", "Evidence Status": DEFAULT_STATUS},
        {"Activity": "Submission, acknowledgements and corrections", "Responsible": "Compliance Operations", "Accountable": "Compliance Owner", "Consulted": "Technology, Tax", "Informed": "Finance, Operations", "Evidence Status": DEFAULT_STATUS},
    ]


def _implementation_milestone_rows() -> list[dict[str, str]]:
    return [
        {"Milestone": "1. Confirm local rules and source evidence", "Build Output": "Approved verification tasks, reporting calendar, schema version and jurisdiction assumptions.", "Exit Criteria": "No production-critical local fact remains unresolved without documented owner/action.", "Primary Owner": "Compliance / Tax", "Evidence Status": DEFAULT_STATUS},
        {"Milestone": "2. Complete source-to-target mapping", "Build Output": "Logical CRS field catalogue mapped to physical extracts/APIs with data lineage and owners.", "Exit Criteria": "All mandatory/conditional fields have source, fallback and missing-data action.", "Primary Owner": "Technology / Data Engineering", "Evidence Status": DEFAULT_STATUS},
        {"Milestone": "3. Build rules, exceptions and controls", "Build Output": "Reportability engine, exception workflow, reconciliation controls and override approvals.", "Exit Criteria": "Controls execute and unresolved mandatory exceptions block final file unless approved.", "Primary Owner": "Technology + Operations", "Evidence Status": DEFAULT_STATUS},
        {"Milestone": "4. Execute UAT and evidence pack", "Build Output": "UAT results, decision traces, reconciliation pack, sample XML and defect closure evidence.", "Exit Criteria": "Positive, negative and edge-case scenarios pass or have approved residual risk.", "Primary Owner": "QA / Compliance Testing", "Evidence Status": DEFAULT_STATUS},
        {"Milestone": "5. File, acknowledge and retain", "Build Output": "Final XML, portal receipt, rejection/correction register and retained approval pack.", "Exit Criteria": "Submission accepted or rejection workflow completed with audit trail.", "Primary Owner": "Compliance Operations", "Evidence Status": DEFAULT_STATUS},
    ]


LOW_VALUE_TITLES = {
    "summary": {"purpose and scope", "needs local confirmation"},
    "architecture": {"source-system mapping", "system of record vs likely source"},
    "field_catalog": {"crs fields", "fields to fetch and derive", "data to fetch from source systems", "data to derive"},
    "downstream": {"xml/schema build requirements", "key dates", "recipient chain"},
    "risk_flags": {"exception/remediation register"},
    "classification": {"classification logic", "entity classification"},
    "governance": {"raci", "implementation timeline"},
    "testing": {"uat scenarios"},
}


def _is_low_value_block(section_key: str, block: dict[str, Any]) -> bool:
    if section_key == "evidence":
        return False
    title = safe_text(block.get("title", "")).lower()
    text = safe_text(block.get("text", "")).lower()
    cols = [safe_text(c).lower() for c in block.get("columns", [])]
    rows = block.get("rows", []) or []
    if title in LOW_VALUE_TITLES.get(section_key, set()):
        return True
    # Drop generic one-row tables from legacy LLM output when deterministic equivalents exist.
    if block.get("type") in {"table", "review_table"} and len(rows) <= 1:
        generic_cols = {"evidence status", "owner", "status", "scenario", "rule", "task"}
        if title in LOW_VALUE_TITLES.get(section_key, set()) or any(c in generic_cols for c in cols):
            return True
    generic_phrases = [
        "this document outlines the implementation blueprint",
        "the fi will use the self-certification forms",
        "report generated correctly",
    ]
    if any(p in text for p in generic_phrases) and section_key in {"summary", "classification", "testing", "governance"}:
        return True
    return False


def _prune_low_value_legacy_blocks(sections: dict[str, Any]) -> None:
    for section_key, section in sections.items():
        blocks = section.get("blocks", []) or []
        section["blocks"] = [b for b in blocks if not _is_low_value_block(section_key, b)]


def _insert_blocks(section: dict, blocks: list[dict[str, Any]], *, prepend: bool = False) -> None:
    existing = section.setdefault("blocks", [])
    if prepend:
        section["blocks"] = blocks + existing
    else:
        existing.extend(blocks)


def apply_implementation_intelligence(structured: dict[str, Any], params: dict | None = None, kb: dict | None = None) -> dict[str, Any]:
    """Add deterministic implementation depth to the structured blueprint."""
    params = params or {}
    kb = kb or {}
    enriched = deepcopy(structured or {})
    enriched["schema_version"] = "2.2"
    sections = enriched.setdefault("sections", {})

    sections.setdefault("summary", {"title": "Executive Summary", "blocks": []})
    _insert_blocks(sections["summary"], _how_to_read_blocks(), prepend=True)
    _insert_blocks(sections["summary"], [{
        "type": "table",
        "title": "Key jurisdiction checks before build lock",
        "columns": ["Check", "Current Signal", "What To Do Before Build Lock", "Evidence Status"],
        "rows": _jurisdiction_quick_check_rows(params, kb),
        "evidence_status": LOCAL_STATUS,
    }, {
        "type": "table",
        "title": "Material jurisdiction-specific implementation differences",
        "columns": ["Area", "What changes in this jurisdiction", "Implementation impact", "Verification task", "Source Layer", "Evidence Status"],
        "rows": _material_difference_rows(params, kb),
        "evidence_status": LOCAL_STATUS,
    }], prepend=False)
    _insert_blocks(sections["summary"], _executive_action_blocks(params, kb), prepend=True)

    sections.setdefault("architecture", {"title": "Data Architecture", "blocks": []})
    _insert_blocks(sections["architecture"], [
        {
            "type": "table",
            "title": "System-to-field matrix",
            "columns": ["Data Item", "Authoritative Source", "Possible Platforms", "Fallback / Remediation", "Not Acceptable Alone", "Control", "Source Layer", "Evidence Status"],
            "rows": _system_to_field_rows(params),
            "evidence_status": DEFAULT_STATUS,
        },
        {
            "type": "table",
            "title": "Selected upstream system guidance",
            "columns": ["System / Platform", "Typical CRS Use", "Do Not Use Alone For", "Implementation Control", "Evidence Status"],
            "rows": _source_profile_rows(params),
            "evidence_status": USER_STATUS,
        },
        {
            "type": "paragraph",
            "title": "Vendor-field warning",
            "text": VENDOR_DISCLAIMER,
            "evidence_status": USER_STATUS,
        },
    ], prepend=True)

    sections.setdefault("field_catalog", {"title": "Field Catalog", "blocks": []})
    _insert_blocks(sections["field_catalog"], [
        {
            "type": "table",
            "title": "Jurisdiction-specific TIN and identifier guidance",
            "columns": ["Requirement Area", "Jurisdiction-Specific Guidance", "Technology Build Instruction", "Verification / Evidence Required", "Source Layer", "Evidence Status"],
            "rows": _tin_guidance_rows(params, kb),
            "evidence_status": LOCAL_STATUS,
        },
        {
            "type": "table",
            "title": "Implementation field catalogue",
            "columns": ["Field", "XML Element", "Requirement", "Source of Record", "Typical Logical Aliases", "Validation / Transformation", "Missing-data Action", "Source Layer", "Evidence Status"],
            "rows": _field_catalog_rows(params, kb),
            "evidence_status": DEFAULT_STATUS,
        },
        {
            "type": "table",
            "title": "Derived field and transformation rules",
            "columns": ["Derived Rule", "Inputs", "Implementation Logic", "Fallback / Limitation", "Reconciliation Control", "Evidence Status"],
            "rows": _derived_rule_rows(params),
            "evidence_status": DEFAULT_STATUS,
        },
    ], prepend=True)

    sections.setdefault("downstream", {"title": "Downstream Reporting", "blocks": []})
    _insert_blocks(sections["downstream"], [
        {
            "type": "table",
            "title": "Downstream build requirements",
            "columns": ["Build Area", "Requirement", "Current Signal", "Technology Instruction", "Evidence / Control", "Evidence Status"],
            "rows": _downstream_rows(kb),
            "evidence_status": DEFAULT_STATUS,
        },
    ], prepend=True)

    sections.setdefault("classification", {"title": "Classification and Due Diligence", "blocks": []})
    _insert_blocks(sections["classification"], [
        {
            "type": "table",
            "title": "Classification decision matrix",
            "columns": ["Decision Point", "Input Data", "Processing Rule", "Exception Action", "Evidence to Retain", "Evidence Status"],
            "rows": _classification_rows(),
            "evidence_status": DEFAULT_STATUS,
        },
    ], prepend=True)

    if "fatca" in sections:
        _insert_blocks(sections["fatca"], [
            {
                "type": "table",
                "title": "FATCA separation and crosswalk controls",
                "columns": ["Area", "FATCA Instruction", "Current Signal", "Technology Guardrail", "Evidence Status"],
                "rows": _fatca_rows(kb),
                "evidence_status": DEFAULT_STATUS,
            },
        ], prepend=True)

    sections.setdefault("risk_flags", {"title": "Risk Flags and Common Gaps", "blocks": []})
    _insert_blocks(sections["risk_flags"], [
        {
            "type": "table",
            "title": "Exception and remediation register",
            "columns": ["Exception", "Detection Rule", "Impact", "Required Action", "Owner / SLA", "Evidence to Retain", "Evidence Status"],
            "rows": _exception_rows(),
            "evidence_status": DEFAULT_STATUS,
        },
    ], prepend=True)

    sections.setdefault("governance", {"title": "Governance and Implementation Timeline", "blocks": []})
    _insert_blocks(sections["governance"], [
        {
            "type": "table",
            "title": "Control framework",
            "columns": ["Control ID", "Objective", "Type", "Owner", "Frequency", "Evidence", "Failure Escalation", "Evidence Status"],
            "rows": _control_rows(),
            "evidence_status": DEFAULT_STATUS,
        },
        {
            "type": "table",
            "title": "Technology build backlog",
            "columns": ["Backlog Item", "Build Requirement", "Acceptance Criteria", "Owner", "Evidence Status"],
            "rows": _backlog_rows(),
            "evidence_status": DEFAULT_STATUS,
        },
        {
            "type": "table",
            "title": "Operations runbook",
            "columns": ["Runbook Step", "Action", "Primary Owner", "Evidence", "Evidence Status"],
            "rows": _operations_runbook_rows(),
            "evidence_status": DEFAULT_STATUS,
        },
        {
            "type": "table",
            "title": "Implementation RACI",
            "columns": ["Activity", "Responsible", "Accountable", "Consulted", "Informed", "Evidence Status"],
            "rows": _raci_rows(),
            "evidence_status": DEFAULT_STATUS,
        },
        {
            "type": "table",
            "title": "Implementation milestone plan",
            "columns": ["Milestone", "Build Output", "Exit Criteria", "Primary Owner", "Evidence Status"],
            "rows": _implementation_milestone_rows(),
            "evidence_status": DEFAULT_STATUS,
        },
    ], prepend=True)

    sections.setdefault("testing", {"title": "Testing and Communication Templates", "blocks": []})
    _insert_blocks(sections["testing"], [
        {
            "type": "table",
            "title": "Implementation-grade UAT scenarios",
            "columns": ["Scenario ID", "Scenario", "Input Data", "Expected Processing", "Acceptance Criteria", "Related Control", "Evidence Status"],
            "rows": _test_rows(),
            "evidence_status": DEFAULT_STATUS,
        },
    ], prepend=True)

    sections.setdefault("evidence", {"title": "Evidence, Assumptions and Review", "blocks": []})
    # Remove the old generic review table if present; replace with precise verification tasks.
    cleaned_evidence_blocks = []
    for block in sections["evidence"].get("blocks", []):
        title = safe_text(block.get("title", "")).lower()
        cols = [safe_text(c).lower() for c in block.get("columns", [])]
        if title in {"needs local confirmation", "local confirmation required", "verification tasks"} and "required action" in cols and "current value" in cols:
            continue
        if "required action" in cols and "current value" in cols and "item" in cols:
            continue
        cleaned_evidence_blocks.append(block)
    sections["evidence"]["blocks"] = cleaned_evidence_blocks
    _insert_blocks(sections["evidence"], [
        {
            "type": "table",
            "title": "Source health and official-site check plan",
            "columns": ["Source", "URL / Location", "Expected Use", "Refresh / Source Status", "Last Verified", "Check Logic", "Evidence Status"],
            "rows": _source_health_rows(kb, params),
            "evidence_status": DEFAULT_STATUS,
        },
        {
            "type": "review_table",
            "title": "Verification task register",
            "columns": ["Verification Task", "Current Signal", "Simple Message", "Where To Check", "Evidence To Retain", "Technology Guardrail", "Evidence Status"],
            "rows": _verification_rows(params, kb),
            "evidence_status": LOCAL_STATUS,
        },
        {
            "type": "table",
            "title": "Implementation completeness indicators",
            "columns": ["Dimension", "Generated Items", "What This Proves", "Evidence Status"],
            "rows": _implementation_completeness_rows(enriched),
            "evidence_status": DEFAULT_STATUS,
        },
    ], prepend=True)

    _prune_low_value_legacy_blocks(sections)

    for section in sections.values():
        _drop_empty_generation_placeholders(section)

    enriched["sections"] = sections
    enriched.setdefault("generation_metadata", {})["implementation_engine"] = "deterministic_templates_v1"
    return enriched
