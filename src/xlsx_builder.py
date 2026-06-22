"""Build a lightweight XLSX implementation workbook from structured CRS Blueprint data.

This writer intentionally uses only the Python standard library so the HuggingFace
Space does not need a heavy spreadsheet dependency.  The workbook is generated
from the same structured blueprint used for the UI and DOCX renderers.
"""
from __future__ import annotations

from datetime import datetime, UTC
from pathlib import Path
from typing import Any
from zipfile import ZipFile, ZIP_DEFLATED
import html
import re

from .structured_blueprint import normalise_structured_result, run_quality_gate, safe_text, display_evidence_status

WORKBOOK_SHEETS = [
    ("Field Catalogue", ["implementation field catalogue"]),
    ("System-to-Field Matrix", ["system-to-field matrix"]),
    ("TIN Guidance", ["jurisdiction-specific tin and identifier guidance"]),
    ("Transformation Rules", ["derived field and transformation rules"]),
    ("Exception Register", ["exception and remediation register"]),
    ("Controls", ["control framework"]),
    ("UAT Scenarios", ["implementation-grade uat scenarios"]),
    ("Verification Tasks", ["verification task register"]),
    ("Sources", ["source health and official-site check plan"]),
    ("Technology Backlog", ["technology build backlog"]),
]


def _xml(text: Any) -> str:
    return html.escape(safe_text(text), quote=True)


def _sheet_name(name: str) -> str:
    cleaned = re.sub(r"[\\/*?:\[\]]", " ", safe_text(name))[:31].strip()
    return cleaned or "Sheet"


def _col_ref(idx: int) -> str:
    out = ""
    while idx:
        idx, rem = divmod(idx - 1, 26)
        out = chr(65 + rem) + out
    return out


def _find_table(structured: dict[str, Any], titles: list[str]) -> tuple[list[str], list[dict[str, Any]]]:
    wanted = {safe_text(t).lower() for t in titles}
    for section in structured.get("sections", {}).values():
        for block in section.get("blocks", []) or []:
            if block.get("type") not in {"table", "review_table"}:
                continue
            title = safe_text(block.get("title", "")).lower()
            if title in wanted:
                return list(block.get("columns", []) or []), list(block.get("rows", []) or [])
    return [], []


def _sheet_xml(columns: list[str], rows: list[dict[str, Any]]) -> str:
    if not columns:
        columns = ["Message"]
        rows = [{"Message": "No structured rows generated for this sheet."}]
    rows_xml = []
    # Header row
    cell_xml = []
    for c_idx, col in enumerate(columns, start=1):
        cell_xml.append(f'<c r="{_col_ref(c_idx)}1" t="inlineStr" s="1"><is><t>{_xml(col)}</t></is></c>')
    rows_xml.append('<row r="1">' + ''.join(cell_xml) + '</row>')
    for r_idx, row in enumerate(rows, start=2):
        cell_xml = []
        for c_idx, col in enumerate(columns, start=1):
            value = row.get(col, "")
            if col == "Evidence Status":
                value = display_evidence_status(value)
            cell_xml.append(f'<c r="{_col_ref(c_idx)}{r_idx}" t="inlineStr" s="2"><is><t>{_xml(value)}</t></is></c>')
        rows_xml.append(f'<row r="{r_idx}">' + ''.join(cell_xml) + '</row>')
    col_widths = ''.join(f'<col min="{i}" max="{i}" width="28" customWidth="1"/>' for i in range(1, len(columns)+1))
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
        f'<cols>{col_widths}</cols>'
        '<sheetData>' + ''.join(rows_xml) + '</sheetData>'
        '</worksheet>'
    )


def _content_types(num_sheets: int) -> str:
    sheets = ''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1, num_sheets+1))
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
        '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
        f'{sheets}</Types>'
    )


def _root_rels() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
        '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
        '</Relationships>'
    )


def _workbook_xml(sheet_names: list[str]) -> str:
    sheets = ''.join(f'<sheet name="{_xml(name)}" sheetId="{idx}" r:id="rId{idx}"/>' for idx, name in enumerate(sheet_names, start=1))
    return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>' + sheets + '</sheets></workbook>'


def _workbook_rels(num_sheets: int) -> str:
    rels = ''.join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, num_sheets+1))
    rels += f'<Relationship Id="rId{num_sheets+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
    return '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + rels + '</Relationships>'


def _styles_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="2"><font><sz val="10"/><name val="Arial"/></font><font><b/><sz val="10"/><color rgb="FF0F2A5F"/><name val="Arial"/></font></fonts>'
        '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FFE9EEF8"/><bgColor indexed="64"/></patternFill></fill></fills>'
        '<borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border><border><left style="thin"/><right style="thin"/><top style="thin"/><bottom style="thin"/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1"/><xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1"><alignment wrapText="1" vertical="top"/></xf></cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        '</styleSheet>'
    )


def build_xlsx(result: dict, params: dict) -> str:
    structured = result.get("_structured_blueprint") if isinstance(result, dict) else None
    if not structured:
        structured = normalise_structured_result(result or {}, params, {})
    # Keep same validation discipline as DOCX, but do not expose diagnostics in workbook.
    run_quality_gate(structured)
    sheet_payloads = []
    for sheet_name, titles in WORKBOOK_SHEETS:
        cols, rows = _find_table(structured, titles)
        sheet_payloads.append((_sheet_name(sheet_name), cols, rows))

    filename = f"CRS_Blueprint_Workbook_{safe_text(params.get('jurisdiction','unknown')).replace(' ', '_') or 'unknown'}_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.xlsx"
    now = datetime.now(UTC).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
    with ZipFile(filename, 'w', ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', _content_types(len(sheet_payloads)))
        z.writestr('_rels/.rels', _root_rels())
        z.writestr('xl/workbook.xml', _workbook_xml([s[0] for s in sheet_payloads]))
        z.writestr('xl/_rels/workbook.xml.rels', _workbook_rels(len(sheet_payloads)))
        z.writestr('xl/styles.xml', _styles_xml())
        z.writestr('docProps/core.xml', f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:title>CRS Blueprint Workbook</dc:title><dc:creator>CRS Blueprint</dc:creator><cp:lastModifiedBy>CRS Blueprint</cp:lastModifiedBy><dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created><dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified></cp:coreProperties>')
        z.writestr('docProps/app.xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"><Application>CRS Blueprint</Application></Properties>')
        for idx, (_, cols, rows) in enumerate(sheet_payloads, start=1):
            z.writestr(f'xl/worksheets/sheet{idx}.xml', _sheet_xml(cols, rows))
    return filename
