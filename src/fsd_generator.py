"""FSD generation: build prompt, call LLM, return structured sections."""
import json
from datetime import date
from pathlib import Path
from .llm_router import call_llm
from .implementation_engine import apply_implementation_intelligence
from .structured_blueprint import (
    SECTION_ORDER,
    SECTION_TITLES,
    normalise_structured_result,
    render_section_markdown,
    render_evidence_markdown,
    run_quality_gate,
    quality_gate_markdown,
)

_REPO_DIR = Path(__file__).parent.parent
KB_DIR = _REPO_DIR / "kb" / "jurisdictions"
KB_COMMON_PATH = _REPO_DIR / "kb" / "common.json"
JURISDICTION_URLS_PATH = _REPO_DIR / "kb" / "jurisdiction_urls.json"
SOURCE_REGISTRY_DIR = _REPO_DIR / "kb" / "source_registry"

SECTION_KEYS = SECTION_ORDER

FALLBACK_SECTIONS = {
    "summary": (
        "FSD generation is unavailable right now. All inference engines are currently down. "
        "Please try again in a few minutes."
    ),
    "architecture": "",
    "field_catalog": "",
    "downstream": "",
    "risk_flags": "",
    "classification": "",
    "governance": "",
    "testing": "",
    "fatca": "",
}


def _load_common() -> dict:
    """Load the OECD common baseline KB."""
    try:
        if KB_COMMON_PATH.exists():
            with open(KB_COMMON_PATH) as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def load_kb(jurisdiction: str) -> dict:
    """Load merged KB: OECD baseline overridden by jurisdiction-specific delta."""
    common = _load_common()

    jur_data: dict = {}
    try:
        with open(JURISDICTION_URLS_PATH) as f:
            url_map = json.load(f)
        entry = url_map.get(jurisdiction, {})
        kb_file = entry.get("kb_file", "")
        if kb_file:
            path = KB_DIR / kb_file
            if path.exists():
                with open(path) as f:
                    jur_data = json.load(f)
    except Exception:
        pass

    # Jurisdiction data wins; common fills gaps
    merged = {**common, **jur_data}

    # Carry forward meta from both
    common_meta = common.get("_meta", {})
    jur_meta = jur_data.get("_meta", {})
    merged["_meta"] = {**common_meta, **jur_meta}
    merged["_common_meta"] = common_meta

    # Registered official-source metadata is used by the implementation
    # intelligence layer. Generation must never depend on an open web search.
    try:
        entry = url_map.get(jurisdiction, {})
        registry = {
            "authority": entry.get("authority", merged.get("authority", "")),
            "local_url": entry.get("local_url", ""),
            "oecd_url": entry.get("oecd_url", ""),
            "allowed_domains": [
                entry.get("local_url", "").split("/")[2] if "//" in entry.get("local_url", "") else "",
                entry.get("oecd_url", "").split("/")[2] if "//" in entry.get("oecd_url", "") else "",
            ],
        }
        code = entry.get("code", "").lower()
        source_file = SOURCE_REGISTRY_DIR / f"{code}.json" if code else None
        if source_file and source_file.exists():
            with open(source_file, encoding="utf-8") as sf:
                registry.update(json.load(sf))
        merged["_source_registry"] = registry
    except Exception:
        merged["_source_registry"] = {}

    return merged


def _staleness_days(kb: dict) -> int:
    """Return age in days of the jurisdiction KB data."""
    try:
        last_updated = kb.get("_meta", {}).get("last_updated", "")
        if last_updated:
            updated = date.fromisoformat(last_updated)
            return (date.today() - updated).days
    except Exception:
        pass
    return 0


def _count_inferred(kb: dict) -> int:
    """Count [INFERRED] tags in the jurisdiction KB."""
    text = json.dumps(kb)
    return text.count("[INFERRED]")


def kb_summary(jurisdiction: str) -> dict:
    """Return structured KB summary for display in the UI."""
    kb = load_kb(jurisdiction)
    meta = kb.get("_meta", {})
    return {
        "confidence": meta.get("confidence", "Unknown"),
        "last_updated": meta.get("last_updated", "Unknown"),
        "staleness_days": _staleness_days(kb),
        "inferred_count": _count_inferred(kb),
        "gaps": meta.get("gaps", []),
        "sources": meta.get("sources", []),
        "authority": kb.get("authority", ""),
        "reporting_deadline": kb.get("reporting_deadline", ""),
        "portal_url": kb.get("portal_url", ""),
        "fatca_iga_type": kb.get("fatca", {}).get("iga_type", ""),
    }


def _build_prompt(params: dict, kb: dict, live_text=None, user_doc_text=None) -> str:
    """Build a strict structured-JSON prompt for the blueprint generator."""
    fi = params["fi_type"]
    jur = params["jurisdiction"]
    up = ", ".join(params.get("upstream_sources") or ["Core Banking System", "Manual / Spreadsheets"])
    acct = ", ".join(params.get("account_types") or ["Individual accounts", "Entity accounts"])
    year = str(params.get("reporting_year", 2024))
    dmin = "Yes" if params.get("de_minimis") else "No"
    grp = "Yes" if params.get("group_fi") else "No"
    include_fatca = bool(params.get("fatca_toggle", False))

    kb_clean = {k: v for k, v in kb.items() if not k.startswith("_")}
    kb_json = json.dumps(kb_clean, indent=2) if kb_clean else "Standard OECD CRS rules apply."
    kb_text = kb_json if len(kb_json) <= 8000 else kb_json[:8000] + "\n... [KB truncated for length]"

    live = ""
    if live_text:
        live = "\n\nLIVE GUIDANCE SUPPLEMENT (use to override KB where they conflict):\n" + live_text[:5000]

    section_keys = SECTION_KEYS + (["fatca"] if include_fatca else [])
    section_names = ", ".join(section_keys)

    schema_example = {
        "schema_version": "2.2",
        "document_status": "Draft for professional review",
        "sections": {
            "summary": {
                "title": "Executive Summary",
                "blocks": [
                    {
                        "type": "paragraph",
                        "title": "Purpose and scope",
                        "text": "One concise implementation-ready statement.",
                        "evidence_status": "User input"
                    },
                    {
                        "type": "numbered_list",
                        "title": "Reportability decision tree",
                        "items": [
                            {"text": "Identify account holder type.", "evidence_status": "Verified"}
                        ]
                    },
                    {
                        "type": "review_table",
                        "title": "Needs local confirmation",
                        "columns": ["Item", "Current Value", "Required Action", "Evidence Status"],
                        "rows": [
                            {
                                "Item": "Exact filing deadline",
                                "Current Value": "Not confirmed in supplied KB",
                                "Required Action": "Verify against current local authority guidance.",
                                "Evidence Status": "Needs verification"
                            }
                        ]
                    }
                ]
            }
        }
    }

    lines = [
        "You are a CRS compliance expert producing a controlled implementation blueprint.",
        "Return ONLY valid JSON. Do not include markdown, pipe tables, code fences, prose before JSON, or prose after JSON.",
        "The output MUST follow this structured schema, not free-form markdown:",
        json.dumps(schema_example, indent=2),
        "",
        "REQUIRED TOP-LEVEL KEYS:",
        "schema_version, document_status, sections",
        "",
        "REQUIRED sections keys: " + section_names + ".",
        "Each section must contain title and blocks.",
        "Allowed block types: paragraph, bullet_list, numbered_list, table, review_table.",
        "Tables must use columns + rows arrays. Do not use markdown pipe syntax.",
        "Lists must use items arrays. Do not number items in the text; the renderer restarts numbering per list.",
        "Every paragraph, list item, and table row must have evidence_status.",
        "Allowed evidence_status values: Verified, User input, Inferred, Local confirmation required.",
        "Every material rule must also answer: what must technology build, where does the data come from, how is it transformed, what happens when missing, what control proves it works.",
        "Use implementation language, not generic policy summaries.",
        "Unsupported, uncertain or jurisdiction-specific facts not explicitly in the KB must be marked Local confirmation required, not written as operational requirements.",
        "Do not fabricate portal names, portal URLs, rejection codes, penalty amounts, local filing deadlines, or local renewal cycles.",
        "Do not recommend fabricated defaults. Prohibited guidance includes: Use default value Unknown; use default values; use last known values; renew every 3 years unless supported by KB or uploaded user documentation.",
        "For missing mandatory values, specify remediation: flag record, outreach/remediate, document reasonable efforts, escalate to Compliance, and confirm permitted reporting treatment locally.",
        "Keep CRS and FATCA separate. US indicia must appear only in the FATCA section/crosswalk when FATCA is included. Do not mix US indicia into CRS reportability logic.",
        "",
        "PARAMETERS:",
        "Jurisdiction: " + jur,
        "FI Type: " + fi,
        "Upstream Systems: " + up,
        "Account Types: " + acct,
        "Reporting Year: " + year,
        "De Minimis Threshold Applicable: " + dmin,
        "Group FI Structure: " + grp,
        "Include FATCA Section: " + ("Yes" if include_fatca else "No"),
        "",
        "JURISDICTION KNOWLEDGE BASE (jurisdiction fields override OECD common defaults):",
        kb_text + live,
        "",
        "SECTION CONTENT REQUIREMENTS:",
        "summary: purpose, scope, confirmed facts, implementation decisions required, reportability decision tree, and concise reviewer tasks.",
        "architecture: source-system mapping, system of record vs likely source, integration points, data lineage, reconciliation controls and data gaps.",
        "field_catalog: rich implementation field catalogue: XML element, requirement state, source of record, logical aliases, validation/transformation, missing-data action, owner/control and evidence status. Never prescribe fake default values.",
        "downstream: reporting obligations, XML/schema build requirements, recipient chain, configurable calendar parameters, portal/submission verification tasks and correction workflow.",
        "risk_flags: exception/remediation register, concrete controls, owners, SLAs, audit evidence and escalation path. No generic risk prose without action.",
        "classification: account holder classification logic, self-certification reliability, entity documentation, Passive NFE look-through and remediation triggers.",
        "governance: RACI, controls, technology backlog, operations runbook, retention and implementation timeline as separate tables.",
        "testing: UAT scenarios with input data, processing rule, expected output, acceptance criteria, negative tests and evidence checks.",
    ]

    if include_fatca:
        fatca_kb = kb_clean.get("fatca", {})
        lines += [
            "fatca: FATCA-only crosswalk with IGA model, FATCA vs CRS differences, dual-reporting workflow, US indicia detection, cure procedures and recalcitrant account handling. Mark local IGA/portal/deadline facts by evidence status.",
            "FATCA KB data: " + (json.dumps(fatca_kb, indent=2) if fatca_kb else "No FATCA KB data available."),
        ]

    if user_doc_text and user_doc_text.strip():
        lines += [
            "",
            "USER-PROVIDED REQUIREMENTS DOCUMENT (use as User input evidence where applicable):",
            user_doc_text[:6000],
        ]

    return "\n".join(lines)


def _fix_markdown(text: str) -> str:
    """
    Ensure Gradio renders tables and lists correctly.
    - Tables need a blank line before the first pipe row.
    - Numbered list items need to be on separate lines.
    - ### headings need a blank line before them.
    """
    import re
    # Pre-process: split LLM's concatenated headings + table rows onto separate lines
    # 1. "### Heading: | col |" -> "### Heading:\n| col |"
    text = re.sub(r'(#{1,4}[^|\n#]+?)\s*\|\s', r'\1\n| ', text)
    # 2. "| row | | row |" -> "| row |\n| row |"
    text = re.sub(r'\|[ \t]*\|', '|\n|', text)
    # 3. "| last row | ### Next heading" -> "| last row |\n\n### Next heading"
    text = re.sub(r'(\|)\s*(#{1,4}\s)', r'\1\n\n\2', text)
    lines = text.split("\n")
    out = []
    for i, line in enumerate(lines):
        prev = out[-1] if out else ""
        stripped = line.strip()

        # Blank line before table rows
        if stripped.startswith("|") and prev.strip() and not prev.strip().startswith("|"):
            out.append("")

        # Blank line before ### headings
        if stripped.startswith("#") and prev.strip() and not prev.strip().startswith("#"):
            out.append("")

        # Blank line after table before non-table content
        if prev.strip().startswith("|") and stripped and not stripped.startswith("|") and not re.match(r"^[-|: ]+$", stripped):
            out.append("")

        out.append(line)

    # Re-join and fix numbered lists run together on one line
    result = "\n".join(out)

    # Split "1. Foo 2. Bar 3. Baz" onto separate lines
    result = re.sub(r"(?<!\n)(\s)(\d+\.\s)", r"\n\2", result)

    # Collapse 3+ blank lines to 2
    result = re.sub(r"\n{3,}", "\n\n", result)

    return result.strip()


def generate_fsd(params: dict, live_text=None, progress=None, user_doc_text=None) -> dict:
    jurisdiction = params["jurisdiction"]
    kb = load_kb(jurisdiction)

    if progress is not None:
        progress(0.1, desc="Loading knowledge base...")

    age = _staleness_days(kb)
    staleness_warning = ""
    if age > 90:
        staleness_warning = (
            "> **KB Staleness Warning**: jurisdiction data is " + str(age) + " days old "
            "(threshold: 90 days). Review [INFERRED] flags carefully and cross-check with official sources."
        )

    if progress is not None:
        progress(0.2, desc="Building prompt...")

    prompt = _build_prompt(params, kb, live_text, user_doc_text)

    if progress is not None:
        progress(0.3, desc="Sending to inference engine...")

    result, attribution, status = call_llm(prompt)

    if progress is not None:
        progress(0.9, desc="Parsing response...")

    if result is None:
        # Produce a complete deterministic implementation blueprint even when
        # optional inference engines are unavailable. The user-facing status must
        # treat this as a successful deterministic generation, not an app failure.
        result = {
            "summary": (
                "Deterministic CRS implementation blueprint generated from curated knowledge-base facts, "
                "jurisdiction overlays and implementation templates. Review official-source verification tasks before use."
            ),
            "architecture": "",
            "field_catalog": "",
            "downstream": "",
            "risk_flags": "",
            "classification": "",
            "governance": "",
            "testing": "",
            "fatca": "" if params.get("fatca_toggle") else "",
        }
        attribution = "Deterministic fallback"
        status = "Blueprint generated using deterministic CRS implementation rules. Optional AI enhancement was unavailable."

    structured = normalise_structured_result(result, params, kb)
    structured = apply_implementation_intelligence(structured, params, kb)
    quality = run_quality_gate(structured)

    # Render controlled markdown for the Gradio HTML layer from structured data only.
    render_keys = SECTION_KEYS + (["fatca"] if params.get("fatca_toggle") else [])
    rendered = {}
    for key in render_keys:
        rendered[key] = render_section_markdown(structured, key)
    if "fatca" not in rendered:
        rendered["fatca"] = ""

    if staleness_warning and rendered.get("summary"):
        rendered["summary"] = staleness_warning + "\n\n" + rendered["summary"]

    evidence_md = render_evidence_markdown(structured)
    total_inferred = sum(
        rendered.get(k, "").count("Inferred") for k in SECTION_KEYS + ["fatca"]
    )
    local_confirmation_count = evidence_md.count("Needs verification") + evidence_md.count("Local confirmation required")

    result_out = {**rendered}
    result_out["evidence"] = evidence_md
    result_out["inferred_count"] = total_inferred
    result_out["local_confirmation_count"] = local_confirmation_count
    result_out["staleness_days"] = age
    result_out["kb_confidence"] = kb.get("_meta", {}).get("confidence", "Unknown")
    result_out["kb_sources"] = kb.get("_meta", {}).get("sources", [])
    result_out["kb_gaps"] = kb.get("_meta", {}).get("gaps", [])
    result_out["status"] = status
    result_out["attribution"] = attribution
    result_out["_structured_blueprint"] = structured
    result_out["_quality_gate"] = quality
    result_out["quality_summary"] = quality_gate_markdown(quality)
    return result_out


# Alias for backward compatibility with tests
_load_kb = load_kb
