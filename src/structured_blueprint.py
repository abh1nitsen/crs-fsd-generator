"""Structured CRS Blueprint schema, rendering, and quality validation.

The LLM should produce structured JSON. This module normalises both the new
schema and legacy markdown responses into one controlled representation so the
UI and DOCX builder never have to parse raw model markdown directly.
"""
from __future__ import annotations

import html
import re
from copy import deepcopy
from typing import Any

SECTION_ORDER = [
    "summary",
    "architecture",
    "field_catalog",
    "downstream",
    "risk_flags",
    "classification",
    "governance",
    "testing",
]

SECTION_TITLES = {
    "summary": "Executive Summary",
    "architecture": "Data Architecture",
    "field_catalog": "Field Catalog",
    "downstream": "Downstream Reporting",
    "risk_flags": "Risk Flags and Common Gaps",
    "classification": "Classification and Due Diligence",
    "governance": "Governance and Implementation Timeline",
    "testing": "Testing and Communication Templates",
    "fatca": "FATCA Crosswalk",
}

EVIDENCE_STATUSES = {
    "Verified",
    "User input",
    "Inferred",
    "Needs verification",
    "Implementation hint",
    # Backward compatibility for legacy cached results/tests. User-facing
    # rendering maps this to "Needs verification".
    "Local confirmation required",
}

USER_FACING_STATUS = {
    "Local confirmation required": "Needs verification",
}


def display_evidence_status(value: Any) -> str:
    """Return the user-facing label for an evidence status."""
    status = normalise_evidence_status(value)
    return USER_FACING_STATUS.get(status, status)

MARKDOWN_TOKEN_RE = re.compile(r"(^|\s)(#{1,6}\s|```|\|\s*[-:]+\s*\|)")
PROHIBITED_PHRASES = [
    "use default value 'unknown'",
    'use default value "unknown"',
    "use default values",
    "use last known values",
    "renew every 3 years",
    "renew every three years",
]

SAFE_REPLACEMENTS = [
    (
        re.compile(r"use\s+default\s+value\s+[\"']?unknown[\"']?", re.I),
        "do not fabricate a mandatory value; flag the record for remediation and confirm permitted handling locally",
    ),
    (
        re.compile(r"use\s+default\s+values", re.I),
        "do not fabricate missing values; flag the record for remediation and document reasonable efforts",
    ),
    (
        re.compile(r"use\s+last\s+known\s+values", re.I),
        "do not rely on stale or unreliable values without documented compliance approval; remediate and obtain current evidence where required",
    ),
    (
        re.compile(r"renew\s+every\s+3\s+years", re.I),
        "review on a change in circumstances and confirm any jurisdiction-specific refresh cycle locally",
    ),
    (
        re.compile(r"renew\s+every\s+three\s+years", re.I),
        "review on a change in circumstances and confirm any jurisdiction-specific refresh cycle locally",
    ),
]

FATCA_ONLY_TERMS = [
    "US place of birth",
    "U.S. place of birth",
    "US phone number",
    "U.S. phone number",
    "US indicia",
    "U.S. indicia",
]


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def normalise_evidence_status(value: Any, default: str = "Needs verification") -> str:
    text = _as_text(value).strip()
    aliases = {
        "verified": "Verified",
        "kb": "Verified",
        "knowledge base": "Verified",
        "official": "Verified",
        "user": "User input",
        "user input": "User input",
        "input": "User input",
        "inferred": "Inferred",
        "model inferred": "Inferred",
        "needs review": "Needs verification",
        "needs local confirmation": "Needs verification",
        "local confirmation required": "Needs verification",
        "needs verification": "Needs verification",
        "unverified": "Needs verification",
        "implementation hint": "Implementation hint",
    }
    return aliases.get(text.lower(), text if text in EVIDENCE_STATUSES else default)


def safe_text(value: Any, *, section_key: str | None = None) -> str:
    """Strip markdown syntax and rewrite unsafe recommendations."""
    text = _as_text(value)
    text = text.replace("\r", " ").replace("\t", " ")
    text = re.sub(r"```+", "", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.M)
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"\*(.*?)\*", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    # Remove table-pipe artefacts from prose. Structured tables are rendered separately.
    text = re.sub(r"\s*\|\s*", " / ", text)
    text = re.sub(r"\s+", " ", text).strip()

    for pattern, replacement in SAFE_REPLACEMENTS:
        text = pattern.sub(replacement, text)

    if section_key != "fatca":
        for term in FATCA_ONLY_TERMS:
            text = re.sub(
                re.escape(term),
                "FATCA-only indicia (handle only in the FATCA crosswalk)",
                text,
                flags=re.I,
            )
    return text


def _split_sentences(text: str, max_items: int = 6) -> list[str]:
    text = safe_text(text)
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+", text)
    cleaned = [p.strip() for p in parts if p.strip()]
    if len(cleaned) <= max_items:
        return cleaned
    head = cleaned[: max_items - 1]
    tail = " ".join(cleaned[max_items - 1 :])
    return head + [tail]


def _infer_status_from_text(text: str) -> str:
    lowered = text.lower()
    if "[inferred]" in lowered or "inferred" in lowered:
        return "Inferred"
    if "confirm" in lowered or "verify" in lowered or "not confirmed" in lowered or "local" in lowered:
        return "Local confirmation required"
    return "User input" if "system" in lowered or "input" in lowered else "Verified"


def _extract_markdown_tables(md: str) -> list[dict[str, Any]]:
    tables: list[dict[str, Any]] = []
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped.startswith("|"):
            i += 1
            continue
        block = []
        while i < len(lines) and lines[i].strip().startswith("|"):
            block.append(lines[i].strip())
            i += 1
        rows = []
        for row in block:
            if re.match(r"^\|?[-| :]+\|?$", row):
                continue
            cells = [safe_text(c) for c in row.strip().strip("|").split("|")]
            rows.append(cells)
        if len(rows) >= 2:
            columns = rows[0]
            row_dicts = []
            for r in rows[1:]:
                row = {columns[c]: r[c] if c < len(r) else "" for c in range(len(columns))}
                if "Evidence Status" not in row:
                    row["Evidence Status"] = "Local confirmation required"
                row_dicts.append(row)
            if "Evidence Status" not in columns:
                columns.append("Evidence Status")
            tables.append({"type": "table", "title": "Structured table", "columns": columns, "rows": row_dicts})
    return tables


def _legacy_section_to_blocks(section_key: str, value: str) -> list[dict[str, Any]]:
    text = _as_text(value)
    tables = _extract_markdown_tables(text)
    # Remove pipe tables from prose after extracting them.
    prose_lines = []
    in_table = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("|"):
            in_table = True
            continue
        if in_table and not stripped:
            in_table = False
            continue
        if not in_table:
            prose_lines.append(line)
    prose = "\n".join(prose_lines)

    blocks: list[dict[str, Any]] = []
    current_title = ""
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_lines, current_title
        raw = " ".join(x.strip() for x in current_lines if x.strip())
        current_lines = []
        if not raw:
            return
        # Numbered list if the paragraph has multiple explicit items.
        list_items = re.split(r"(?:^|\s)(?:\d+\.)\s+", raw)
        list_items = [safe_text(item, section_key=section_key) for item in list_items if item.strip()]
        if len(list_items) >= 3:
            blocks.append({
                "type": "numbered_list",
                "title": current_title or "Key steps",
                "items": [{"text": item, "evidence_status": _infer_status_from_text(item)} for item in list_items],
                "evidence_status": "Needs verification",
            })
        else:
            for sentence in _split_sentences(raw):
                blocks.append({
                    "type": "paragraph",
                    "title": current_title,
                    "text": sentence,
                    "evidence_status": _infer_status_from_text(sentence),
                })
                current_title = ""

    for line in prose.splitlines():
        stripped = line.strip()
        if not stripped:
            flush()
            continue
        heading = re.match(r"^#{1,6}\s+(.+)$", stripped)
        if heading:
            flush()
            heading_text = safe_text(heading.group(1), section_key=section_key)
            if heading_text.lower() != SECTION_TITLES.get(section_key, "").lower():
                current_title = heading_text
            continue
        bullet = re.match(r"^(?:[-*]|\d+\.)\s+(.+)$", stripped)
        if bullet:
            flush()
            item = safe_text(bullet.group(1), section_key=section_key)
            blocks.append({
                "type": "numbered_list" if re.match(r"^\d+\.", stripped) else "bullet_list",
                "title": current_title or "Review item",
                "items": [{"text": item, "evidence_status": _infer_status_from_text(item)}],
                "evidence_status": _infer_status_from_text(item),
            })
            current_title = ""
            continue
        current_lines.append(stripped)
    flush()
    blocks.extend(tables)
    if not blocks:
        blocks.append({
            "type": "paragraph",
            "title": "Not generated",
            "text": "This section was not generated. Regenerate the blueprint or complete this section manually.",
            "evidence_status": "Needs verification",
        })
    return blocks


def _normalise_block(section_key: str, block: Any) -> dict[str, Any] | None:
    if isinstance(block, str):
        text = safe_text(block, section_key=section_key)
        if not text:
            return None
        return {"type": "paragraph", "text": text, "evidence_status": _infer_status_from_text(text)}
    if not isinstance(block, dict):
        return None
    b = deepcopy(block)
    btype = _as_text(b.get("type") or b.get("block_type") or "paragraph").strip().lower()
    if btype in {"list", "ordered_list"}:
        btype = "numbered_list"
    if btype in {"bullets", "unordered_list"}:
        btype = "bullet_list"
    if btype not in {"paragraph", "bullet_list", "numbered_list", "table", "review_table"}:
        btype = "paragraph"
    b["type"] = btype
    b["title"] = safe_text(b.get("title", ""), section_key=section_key)
    b["evidence_status"] = normalise_evidence_status(b.get("evidence_status"))

    if btype == "table" or btype == "review_table":
        columns = b.get("columns") or []
        if isinstance(columns, str):
            columns = [c.strip() for c in columns.split(",")]
        columns = [safe_text(c, section_key=section_key) for c in columns if safe_text(c, section_key=section_key)]
        rows = b.get("rows") or []
        normal_rows = []
        if isinstance(rows, dict):
            rows = [rows]
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, list):
                    row_dict = {columns[i] if i < len(columns) else f"Column {i+1}": row[i] for i in range(len(row))}
                elif isinstance(row, dict):
                    row_dict = row
                else:
                    continue
                cleaned = {safe_text(k, section_key=section_key): safe_text(v, section_key=section_key) for k, v in row_dict.items() if safe_text(k)}
                if cleaned:
                    cleaned["Evidence Status"] = normalise_evidence_status(cleaned.get("Evidence Status") or cleaned.get("evidence_status") or b["evidence_status"])
                    cleaned.pop("evidence_status", None)
                    normal_rows.append(cleaned)
        if not columns and normal_rows:
            columns = [c for c in normal_rows[0].keys() if c != "Evidence Status"]
        if "Evidence Status" not in columns:
            columns.append("Evidence Status")
        b["columns"] = columns
        b["rows"] = normal_rows
        return b if normal_rows else None

    if btype in {"bullet_list", "numbered_list"}:
        items = b.get("items") or []
        if isinstance(items, str):
            items = [items]
        normal_items = []
        for item in items:
            if isinstance(item, dict):
                text = safe_text(item.get("text") or item.get("item") or "", section_key=section_key)
                status = normalise_evidence_status(item.get("evidence_status") or b["evidence_status"])
            else:
                text = safe_text(item, section_key=section_key)
                status = _infer_status_from_text(text)
            if text:
                normal_items.append({"text": text, "evidence_status": status})
        b["items"] = normal_items
        return b if normal_items else None

    text = safe_text(b.get("text") or b.get("content") or b.get("rule") or "", section_key=section_key)
    b["text"] = text
    return b if text else None


def _default_review_items(params: dict, kb: dict) -> list[dict[str, str]]:
    jur = params.get("jurisdiction", "Selected jurisdiction")
    items = [
        {
            "Item": "Competent authority",
            "Current Value": safe_text(kb.get("authority") or "Not confirmed"),
            "Required Action": "Verify against the current local tax authority CRS guidance before implementation.",
            "Evidence Status": "Needs verification",
        },
        {
            "Item": "Filing deadline",
            "Current Value": safe_text(kb.get("reporting_deadline") or "Not confirmed"),
            "Required Action": "Confirm the exact filing date for the reporting year and institution type.",
            "Evidence Status": "Needs verification",
        },
        {
            "Item": "Submission portal and rejection codes",
            "Current Value": safe_text(kb.get("portal_url") or "Not confirmed"),
            "Required Action": "Confirm the portal, schema validations and rejection/error code handling locally.",
            "Evidence Status": "Needs verification",
        },
    ]
    return items


def legacy_to_structured(result: dict[str, Any], params: dict | None = None, kb: dict | None = None) -> dict[str, Any]:
    params = params or {}
    kb = kb or {}
    include_fatca = bool(params.get("fatca_toggle") or result.get("fatca"))
    order = SECTION_ORDER + (["fatca"] if include_fatca else [])
    sections = {}
    for key in order:
        sections[key] = {
            "title": SECTION_TITLES.get(key, key.replace("_", " ").title()),
            "blocks": _legacy_section_to_blocks(key, _as_text(result.get(key, ""))),
        }

    review_rows = _default_review_items(params, kb)
    sections.setdefault("evidence", {
        "title": "Evidence, Assumptions and Review",
        "blocks": [],
    })
    sections["evidence"]["blocks"].append({
        "type": "review_table",
        "title": "Verification tasks",
        "columns": ["Item", "Current Value", "Required Action", "Evidence Status"],
        "rows": review_rows,
        "evidence_status": "Needs verification",
    })

    return {
        "schema_version": "2.1",
        "document_status": "Implementation draft",
        "sections": sections,
        "generation_metadata": {
            "jurisdiction": params.get("jurisdiction", ""),
            "fi_type": params.get("fi_type", ""),
            "reporting_year": params.get("reporting_year", ""),
        },
    }


def normalise_structured_result(raw: dict[str, Any], params: dict | None = None, kb: dict | None = None) -> dict[str, Any]:
    """Return a canonical structured blueprint from new-schema or legacy output."""
    params = params or {}
    kb = kb or {}
    if isinstance(raw, dict) and isinstance(raw.get("sections"), dict):
        structured = deepcopy(raw)
        structured.setdefault("schema_version", "2.1")
        structured.setdefault("document_status", "Implementation draft")
        sections = {}
        include_fatca = bool(params.get("fatca_toggle") or raw.get("sections", {}).get("fatca"))
        order = SECTION_ORDER + (["fatca"] if include_fatca else [])
        for key in order:
            sec = raw.get("sections", {}).get(key, {})
            if isinstance(sec, str):
                sec = {"title": SECTION_TITLES.get(key, key), "blocks": _legacy_section_to_blocks(key, sec)}
            title = safe_text(sec.get("title") if isinstance(sec, dict) else "", section_key=key) or SECTION_TITLES.get(key, key)
            blocks_in = sec.get("blocks", []) if isinstance(sec, dict) else []
            if isinstance(blocks_in, dict):
                blocks_in = [blocks_in]
            blocks = []
            for block in blocks_in:
                norm = _normalise_block(key, block)
                if norm:
                    blocks.append(norm)
            if not blocks:
                blocks = _legacy_section_to_blocks(key, _as_text(raw.get(key, "")))
            sections[key] = {"title": title, "blocks": blocks}
        evidence_sec = raw.get("sections", {}).get("evidence") or raw.get("evidence_assumptions") or {}
        evidence_blocks = []
        if isinstance(evidence_sec, dict):
            for block in evidence_sec.get("blocks", []):
                norm = _normalise_block("evidence", block)
                if norm:
                    evidence_blocks.append(norm)
        evidence_blocks.append({
            "type": "review_table",
            "title": "Verification tasks",
            "columns": ["Item", "Current Value", "Required Action", "Evidence Status"],
            "rows": _default_review_items(params, kb),
            "evidence_status": "Needs verification",
        })
        sections["evidence"] = {"title": "Evidence, Assumptions and Review", "blocks": evidence_blocks}
        structured["sections"] = sections
        structured.setdefault("generation_metadata", {})
        structured["generation_metadata"].update({
            "jurisdiction": params.get("jurisdiction", structured["generation_metadata"].get("jurisdiction", "")),
            "fi_type": params.get("fi_type", structured["generation_metadata"].get("fi_type", "")),
            "reporting_year": params.get("reporting_year", structured["generation_metadata"].get("reporting_year", "")),
        })
        return structured
    return legacy_to_structured(raw or {}, params, kb)


def _escape_md_cell(value: Any) -> str:
    text = safe_text(value).replace("|", "/")
    return text


def render_section_markdown(structured: dict[str, Any], section_key: str) -> str:
    section = structured.get("sections", {}).get(section_key, {})
    title = section.get("title") or SECTION_TITLES.get(section_key, section_key.title())
    out = [f"## {title}", ""]
    for block in section.get("blocks", []):
        title = block.get("title")
        if title:
            out += [f"### {safe_text(title)}", ""]
        btype = block.get("type")
        if btype in {"table", "review_table"}:
            columns = block.get("columns") or []
            rows = block.get("rows") or []
            if columns and rows:
                out.append("| " + " | ".join(_escape_md_cell(c) for c in columns) + " |")
                out.append("| " + " | ".join("---" for _ in columns) + " |")
                for row in rows:
                    display_row = dict(row)
                    if "Evidence Status" in display_row:
                        display_row["Evidence Status"] = display_evidence_status(display_row.get("Evidence Status"))
                    out.append("| " + " | ".join(_escape_md_cell(display_row.get(c, "")) for c in columns) + " |")
                out.append("")
        elif btype == "numbered_list":
            for idx, item in enumerate(block.get("items", []), start=1):
                status = display_evidence_status(item.get("evidence_status"))
                out.append(f"{idx}. {safe_text(item.get('text'))} **[{status}]**")
            out.append("")
        elif btype == "bullet_list":
            for item in block.get("items", []):
                status = display_evidence_status(item.get("evidence_status"))
                out.append(f"- {safe_text(item.get('text'))} **[{status}]**")
            out.append("")
        else:
            status = display_evidence_status(block.get("evidence_status"))
            out.append(safe_text(block.get("text")))
            out.append("")
            out.append(f"*Evidence status: {status}*")
            out.append("")
    return "\n".join(out).strip()


def render_evidence_markdown(structured: dict[str, Any]) -> str:
    return render_section_markdown(structured, "evidence")


def _iter_text_values(value: Any):
    if isinstance(value, dict):
        for v in value.values():
            yield from _iter_text_values(v)
    elif isinstance(value, list):
        for v in value:
            yield from _iter_text_values(v)
    elif isinstance(value, str):
        yield value


def run_quality_gate(structured: dict[str, Any]) -> dict[str, Any]:
    text_values = list(_iter_text_values(structured))
    joined = "\n".join(text_values)
    required_sections = [k for k in SECTION_ORDER if k not in structured.get("sections", {})]
    raw_markdown = [t for t in text_values if MARKDOWN_TOKEN_RE.search(t)]
    prohibited = [p for p in PROHIBITED_PHRASES if p in joined.lower()]

    missing_evidence = []
    for sec_key, sec in structured.get("sections", {}).items():
        for idx, block in enumerate(sec.get("blocks", []), start=1):
            btype = block.get("type")
            if btype in {"paragraph", "table", "review_table"} and normalise_evidence_status(block.get("evidence_status")) not in EVIDENCE_STATUSES:
                missing_evidence.append(f"{sec_key} block {idx}")
            if btype in {"bullet_list", "numbered_list"}:
                for item_idx, item in enumerate(block.get("items", []), start=1):
                    if normalise_evidence_status(item.get("evidence_status")) not in EVIDENCE_STATUSES:
                        missing_evidence.append(f"{sec_key} item {item_idx}")
            if btype in {"table", "review_table"}:
                if not block.get("rows") or not block.get("columns"):
                    missing_evidence.append(f"{sec_key} table {idx} empty")
                for row_idx, row in enumerate(block.get("rows", []), start=1):
                    if normalise_evidence_status(row.get("Evidence Status")) not in EVIDENCE_STATUSES:
                        missing_evidence.append(f"{sec_key} table {idx} row {row_idx}")

    verification_items = [t for t in text_values if "Needs verification" in t or "Local confirmation required" in t or ("verify" in t.lower() or "confirm" in t.lower())]
    checks = [
        {"name": "Structured JSON valid", "passed": isinstance(structured.get("sections"), dict)},
        {"name": "Required sections present", "passed": not required_sections, "detail": ", ".join(required_sections)},
        {"name": "No raw markdown leakage", "passed": not raw_markdown, "detail": str(len(raw_markdown)) + " raw tokens found" if raw_markdown else ""},
        {"name": "No prohibited defaulting language", "passed": not prohibited, "detail": ", ".join(prohibited)},
        {"name": "Evidence statuses present", "passed": not missing_evidence, "detail": ", ".join(missing_evidence[:5])},
        {"name": "Verification tasks captured", "passed": bool(verification_items)},
    ]
    passed = all(c["passed"] for c in checks)
    issues = [c for c in checks if not c["passed"]]
    return {"passed": passed, "checks": checks, "issues": issues}


def quality_gate_markdown(quality: dict[str, Any]) -> str:
    status = "passed" if quality.get("passed") else "failed"
    lines = [f"**Generation diagnostics {status}.**", ""]
    for check in quality.get("checks", []):
        icon = "✓" if check.get("passed") else "✕"
        detail = (" - " + check.get("detail", "")) if check.get("detail") else ""
        lines.append(f"{icon} {check.get('name')}{detail}")
    return "\n".join(lines)


def quality_gate_html(quality: dict[str, Any]) -> str:
    status = "passed" if quality.get("passed") else "failed"
    badge = "quality-pass" if quality.get("passed") else "quality-fail"
    rows = []
    for check in quality.get("checks", []):
        cls = "pass" if check.get("passed") else "fail"
        icon = "✓" if check.get("passed") else "✕"
        detail = html.escape(check.get("detail", ""))
        rows.append(
            f'<div class="quality-row {cls}"><span>{icon}</span><b>{html.escape(check.get("name", ""))}</b>'
            + (f'<small>{detail}</small>' if detail else "")
            + "</div>"
        )
    return (
        '<div class="quality-panel">'
        f'<div class="quality-panel-title">Generation diagnostics <span class="{badge}">{status}</span></div>'
        + "".join(rows)
        + "</div>"
    )
