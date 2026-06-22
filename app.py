"""CRS Blueprint - Gradio app for Hugging Face Spaces."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json
import datetime
import gradio as gr
from pathlib import Path
from src.fsd_generator import generate_fsd, load_kb, kb_summary
from src.cache_manager import get_cache, set_cache, cache_age_label
from src.docx_builder import build_docx
from src.xlsx_builder import build_xlsx
from src.doc_fetcher import fetch_latest_guidance
from src.doc_parser import parse_uploaded_doc
from src.structured_blueprint import quality_gate_html
from src.source_health import freshness_from_registry

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DATA_DIR = Path("/data")          # persistent in HF Spaces
USAGE_FILE = DATA_DIR / "usage.json"

# Rate limits — override via HF Space secrets without code changes:
#   ANON_LIMIT=999       → unlimited for testing
#   AUTH_MONTHLY_LIMIT=999 → unlimited logged-in for testing
_anon_env = os.environ.get("ANON_LIMIT", "")
ANON_LIMIT = int(_anon_env) if _anon_env.isdigit() else 1
_auth_env = os.environ.get("AUTH_MONTHLY_LIMIT", "")
AUTH_MONTHLY_LIMIT = int(_auth_env) if _auth_env.isdigit() else 10
LINKEDIN_URL = "https://www.linkedin.com/in/abhinit-sen-63443015/"
STALENESS_WARN_DAYS = 90

# ---------------------------------------------------------------------------
# Load static data
# ---------------------------------------------------------------------------
with open("data/fi_types.json") as f:
    FI_TYPES = json.load(f)

with open("kb/jurisdiction_urls.json") as f:
    JURISDICTION_URLS = json.load(f)

ENRICHED_JURISDICTIONS = {
    "Australia", "United Kingdom", "Germany", "France", "Luxembourg",
    "Switzerland", "Singapore", "Hong Kong", "United Arab Emirates",
    "Netherlands", "Japan",
}

JURISDICTION_LIST = [
    ("★ " + k if k in ENRICHED_JURISDICTIONS else k, k)
    for k in sorted(JURISDICTION_URLS.keys())
]
FI_LABELS = [ft["label"] for ft in FI_TYPES]
FI_MAP = {ft["label"]: ft for ft in FI_TYPES}

UPSTREAM_CHOICES = [
    "Core Banking System",
    "Temenos Transact / T24",
    "Oracle Flexcube",
    "Infosys Finacle",
    "Avaloq",
    "Murex",
    "Calypso / Adenza",
    "CRM / Customer Onboarding Platform",
    "Salesforce",
    "Microsoft Dynamics CRM",
    "KYC / AML System",
    "Fenergo",
    "Custody / Securities Platform",
    "Fund Administration Platform",
    "Corporate Actions Platform",
    "General Ledger",
    "Enterprise Data Warehouse",
    "Manual / Spreadsheets",
    "Third-party Data Vendor",
]

# ---------------------------------------------------------------------------
# Rate limiting helpers
# ---------------------------------------------------------------------------
def _load_usage() -> dict:
    try:
        if USAGE_FILE.exists():
            with open(USAGE_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return {"monthly": {}}


def _save_usage(data: dict):
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(USAGE_FILE, "w") as f:
            json.dump(data, f)
    except Exception:
        pass


def _monthly_key(user_id: str) -> str:
    month = datetime.date.today().strftime("%Y-%m")
    return user_id + "_" + month


def check_rate_limit(anon_count: int, profile) -> tuple:
    """Return (allowed: bool, message: str)."""
    if profile is None:
        if anon_count >= ANON_LIMIT:
            lines = [
                "**Free limit reached.** Anonymous use is limited to "
                + str(ANON_LIMIT) + " Blueprint per session.",
                "",
                "To continue, either:",
                "- **Log in with your Hugging Face account** (free, gives "
                + str(AUTH_MONTHLY_LIMIT) + " Blueprints/month), or",
                "- **[Contact Abhinit Sen on LinkedIn](" + LINKEDIN_URL + ")** for project-specific support.",
            ]
            return False, "\n".join(lines)
        return True, ""
    else:
        try:
            user_id = profile.username
        except Exception:
            user_id = str(profile)
        usage = _load_usage()
        key = _monthly_key(user_id)
        count = usage.get("monthly", {}).get(key, 0)
        if count >= AUTH_MONTHLY_LIMIT:
            lines = [
                "**Monthly limit reached.** Logged-in accounts are limited to "
                + str(AUTH_MONTHLY_LIMIT) + " Blueprints per calendar month.",
                "",
                "For project-specific support, "
                "[contact Abhinit Sen on LinkedIn](" + LINKEDIN_URL + ").",
            ]
            return False, "\n".join(lines)
        return True, ""


def increment_usage(anon_count: int, profile) -> int:
    """Increment counter; return new anon_count."""
    if profile is None:
        return anon_count + 1
    try:
        user_id = profile.username
    except Exception:
        user_id = str(profile)
    usage = _load_usage()
    key = _monthly_key(user_id)
    usage.setdefault("monthly", {})[key] = usage["monthly"].get(key, 0) + 1
    _save_usage(usage)
    return anon_count  # unchanged for logged-in users



# ---------------------------------------------------------------------------
# HTML rendering helper (replaces gr.Markdown for section outputs)
# ---------------------------------------------------------------------------
FATCA_PLACEHOLDER_HTML = (
    '<div class="fsd-content" style="color:#6b7280;padding:32px;text-align:center;">' +
    '<p>Enable <strong>Include FATCA crosswalk section</strong> ' +
    'in Step 4 Advanced options, then click Generate Blueprint ' +
    'to populate this section.</p></div>'
)


def md_to_html(text: str) -> str:
    """Convert markdown to HTML. Uses markdown library if available, else inline converter."""
    if not text or not text.strip():
        return ""
    try:
        import markdown as _md
        html = _md.markdown(text, extensions=["tables", "fenced_code"])
        return '<div class="fsd-content">' + _wrap_tables_for_ui(html) + '</div>'
    except Exception:
        pass
    return _md_to_html_inline(text)


def _wrap_tables_for_ui(html: str) -> str:
    """Wrap rendered tables so wide implementation grids scroll instead of clipping."""
    import re
    if not html or '<table' not in html:
        return html

    def repl(match):
        attrs = match.group(1) or ""
        if 'class=' in attrs:
            attrs = re.sub(r'class="([^"]*)"', r'class="\1 wide-table"', attrs, count=1)
            attrs = re.sub(r"class='([^']*)'", r"class='\1 wide-table'", attrs, count=1)
        else:
            attrs = attrs + ' class="wide-table"'
        return '<div class="table-scroll" role="region" aria-label="Scrollable implementation table"><table' + attrs + '>'

    html = re.sub(r'<table\b([^>]*)>', repl, html)
    return html.replace('</table>', '</table></div>')


def _md_to_html_inline(text: str) -> str:
    """Pure-Python markdown->HTML: handles tables, headers, bold, lists."""
    import re
    # Pre-process: split LLM's concatenated headings + table rows
    text = re.sub(r'(#{1,4}[^|\n#]+?)\s*\|\s', r'\1\n| ', text)
    text = re.sub(r'\|[ \t]*\|', '|\n|', text)
    text = re.sub(r'(\|)\s*(#{1,4}\s)', r'\1\n\n\2', text)
    lines = text.split("\n")
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Table: collect consecutive pipe rows
        if stripped.startswith("|"):
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i].strip())
                i += 1
            # Split into header, separator, body
            data = [r for r in table_lines if not re.match(r"^\|[-| :]+\|$", r)]
            if data:
                rows_html = []
                for ri, row in enumerate(data):
                    cells = [c.strip() for c in row.strip("|").split("|")]
                    tag = "th" if ri == 0 else "td"
                    cells_html = "".join(f"<{tag}>{_inline(c)}</{tag}>" for c in cells)
                    rows_html.append(f"<tr>{cells_html}</tr>")
                out.append('<div class="table-scroll" role="region" aria-label="Scrollable implementation table"><table class="wide-table"><thead>' + rows_html[0] + "</thead><tbody>" +
                           "".join(rows_html[1:]) + "</tbody></table></div>")
            continue

        # Headers
        m = re.match(r"^(#{1,4})\s+(.*)", stripped)
        if m:
            lvl = len(m.group(1))
            out.append(f"<h{lvl}>{_inline(m.group(2))}</h{lvl}>")
            i += 1
            continue

        # Bullet
        if stripped.startswith("- ") or stripped.startswith("* "):
            items = []
            while i < len(lines) and re.match(r"^[-*]\s", lines[i].strip()):
                items.append(f"<li>{_inline(lines[i].strip()[2:])}</li>")
                i += 1
            out.append("<ul>" + "".join(items) + "</ul>")
            continue

        # Numbered list
        if re.match(r"^\d+\.\s", stripped):
            items = []
            while i < len(lines) and re.match(r"^\d+\.\s", lines[i].strip()):
                content = re.sub(r"^\d+\.\s+", "", lines[i].strip())
                items.append("<li>" + _inline(content) + "</li>")
                i += 1
            out.append("<ol>" + "".join(items) + "</ol>")
            continue

        # Blockquote
        if stripped.startswith("> "):
            out.append(f"<blockquote>{_inline(stripped[2:])}</blockquote>")
            i += 1
            continue

        # Blank line
        if not stripped:
            out.append("")
            i += 1
            continue

        # Normal paragraph
        out.append(f"<p>{_inline(stripped)}</p>")
        i += 1

    return '<div class="fsd-content">' + "\n".join(out) + '</div>'


def _inline(text: str) -> str:
    """Convert inline markdown (bold, italic, code) to HTML."""
    import re
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2" target="_blank">\1</a>', text)
    return text


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------
CSS = """
:root {
    --crs-navy: #0f172a;
    --crs-indigo: #1d4ed8;
    --crs-indigo-dark: #1e40af;
    --crs-accent: #0f766e;
    --crs-ink: #0f172a;
    --crs-muted: #475569;
    --crs-line: #e2e8f0;
    --crs-surface: #ffffff;
    --crs-canvas: #f6f8fb;
    --crs-warning-bg: #fffbeb;
    --crs-warning: #92400e;
}
body, .gradio-container { font-family: 'Inter', ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important; }
.gradio-container {
    max-width: 1440px !important;
    margin: 0 auto !important;
    padding: 18px 24px 32px !important;
    background: var(--crs-canvas) !important;
    color: var(--crs-ink);
}
.crs-header {
    display: flex; align-items: center; justify-content: space-between; gap: 24px;
    padding: 8px 2px 18px;
}
.crs-header h1 { margin: 0; color: var(--crs-navy); font-size: 34px; line-height: 1.1; letter-spacing: -0.03em; }
.crs-header .promise { margin: 8px 0 3px; color: var(--crs-ink); font-size: 17px; font-weight: 650; }
.crs-header .descriptor { margin: 0; color: var(--crs-muted); font-size: 14px; }
.header-login { display: flex; justify-content: flex-end; align-items: center; }
.disclaimer-banner {
    background: var(--crs-warning-bg); border: 1px solid #f6c453;
    border-left: 5px solid #d97706; border-radius: 10px;
    padding: 14px 18px; margin: 0 0 18px 0;
    font-size: 13.5px; color: #78350f; line-height: 1.55;
    box-shadow: 0 1px 2px rgba(15, 23, 42, .04);
}
.disclaimer-banner strong { display: block; margin-bottom: 3px; color: #7c2d12; font-size: 14px; }
#workspace-grid { align-items: flex-start; gap: 18px; }
#input-wizard {
    position: sticky; top: 12px; align-self: flex-start;
    max-height: calc(100vh - 24px); overflow-y: auto; padding-right: 5px;
    scrollbar-width: thin;
}
.step-card {
    background: var(--crs-surface) !important; border: 1px solid var(--crs-line) !important;
    border-radius: 12px !important; padding: 14px !important; margin-bottom: 12px !important;
    box-shadow: 0 1px 2px rgba(15, 23, 42, .04);
}
.step-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 9px; }
.step-number {
    display: inline-flex; align-items: center; justify-content: center;
    width: 25px; height: 25px; border-radius: 8px; margin-right: 8px;
    background: #eff6ff; color: var(--crs-indigo-dark); font-size: 12px; font-weight: 800;
}
.step-title { color: var(--crs-navy); font-size: 14px; font-weight: 750; }
.step-required, .step-optional, .step-complete {
    display: inline-block; border-radius: 999px; padding: 3px 8px; font-size: 11px; font-weight: 700;
}
.step-required { background: #fff1f2; color: #be123c; }
.step-optional { background: #f1f5f9; color: #475569; }
.step-complete { background: #ecfdf5; color: #047857; }
.enriched-legend { margin: 5px 0 9px; color: #475569; font-size: 12px; line-height: 1.45; }
.jurisdiction-card {
    margin-top: 9px; padding: 11px 12px; border-radius: 9px;
    border: 1px solid #c7d2fe; background: #f8faff; color: #334155; font-size: 12px;
}
.jurisdiction-card strong { color: var(--crs-navy); font-size: 13px; }
.jurisdiction-meta { display: grid; grid-template-columns: 1fr 1fr; gap: 5px 12px; margin-top: 8px; }
.source-selector label { border-radius: 8px !important; }
.source-guide { font-size: 12px; color: #64748b; line-height: 1.5; margin-top: 7px; }
.source-guide b { color: #334155; }
#requirements-upload { min-height: 92px !important; }
#generate-action {
    position: sticky; bottom: 0; z-index: 4; padding: 10px 0 2px;
    background: linear-gradient(to top, var(--crs-canvas) 78%, rgba(246,248,252,0));
}
#generate-btn {
    background: var(--crs-indigo) !important; border: none !important;
    font-size: 15px !important; font-weight: 750 !important;
    border-radius: 9px !important; padding: 13px !important;
    box-shadow: 0 7px 18px rgba(29, 78, 216, .18);
}
#generate-btn:hover { background: var(--crs-indigo-dark) !important; }
#results-workspace {
    background: var(--crs-surface); border: 1px solid var(--crs-line); border-radius: 14px;
    padding: 16px; min-height: 680px; box-shadow: 0 4px 18px rgba(15, 23, 42, .06);
}
.result-header {
    display: flex; align-items: flex-start; justify-content: space-between; gap: 18px;
    padding: 2px 2px 13px; border-bottom: 1px solid #e8edf5; margin-bottom: 12px;
}
.result-header h2 { margin: 0; color: var(--crs-navy); font-size: 20px; }
.result-header p { margin: 4px 0 0; color: var(--crs-muted); font-size: 13px; }
.status-card {
    border: 1px solid #cbd5e1; border-left: 4px solid var(--crs-indigo);
    background: #f8fafc; border-radius: 9px; padding: 10px 13px; margin-bottom: 12px;
    color: #334155; font-size: 13px;
}
.status-card p { margin: 0; }

.quality-panel {
    border: 1px solid #dbe3ef; background: #f8fafc; border-radius: 10px;
    padding: 11px 13px; margin: 0 0 12px; font-size: 12.5px;
}
.quality-panel-title { color: var(--crs-navy); font-weight: 800; margin-bottom: 8px; display: flex; gap: 8px; align-items: center; }
.quality-pass, .quality-fail { border-radius: 999px; padding: 2px 8px; font-size: 11px; text-transform: uppercase; }
.quality-pass { background: #ecfdf5; color: #047857; }
.quality-fail { background: #fff1f2; color: #be123c; }
.quality-row { display: grid; grid-template-columns: 18px minmax(150px, 240px) 1fr; gap: 7px; align-items: start; padding: 3px 0; }
.quality-row.pass span { color: #047857; font-weight: 800; }
.quality-row.fail span { color: #be123c; font-weight: 800; }
.quality-row small { color: #64748b; line-height: 1.45; }
.review-banner { background:#fff7ed; border:1px solid #fed7aa; color:#9a3412; border-radius:9px; padding:9px 12px; margin:0 0 12px; font-size:12.5px; }
.result-actions { align-items: center; margin-bottom: 12px; }
.result-actions button { min-height: 39px; font-weight: 700 !important; }
.result-groups > .tab-nav { gap: 5px; border-bottom: 1px solid #e2e8f0; }
.result-groups button { font-size: 13px !important; font-weight: 650 !important; padding: 9px 12px !important; }
.result-groups button.selected { color: var(--crs-indigo-dark) !important; border-bottom-color: var(--crs-indigo) !important; }
.nested-tabs button { font-size: 12.5px !important; }
.fsd-content { font-size: 14px; line-height: 1.72; max-width: 100%; overflow: visible; }
.table-scroll {
    width: 100%; max-width: 100%; overflow-x: auto; overflow-y: hidden;
    margin: 16px 0 18px; border: 1px solid #dbe3ef; border-radius: 9px;
    background: #ffffff; box-shadow: inset -12px 0 16px -18px rgba(15, 23, 42, .45);
}
.table-scroll::before {
    content: "Wide table — scroll sideways to view all columns";
    display: block; padding: 6px 10px; font-size: 11.5px; color: #64748b;
    background: #f8fafc; border-bottom: 1px solid #e2e8f0;
}
.fsd-content table { border-collapse: separate; border-spacing: 0; width: max-content; min-width: 1080px; margin: 0; font-size: 12.5px; table-layout: auto; background: #ffffff; }
.fsd-content thead { background: #f1f5f9; }
.fsd-content th, .fsd-content td { border-right: 1px solid #e2e8f0; border-bottom: 1px solid #e2e8f0; padding: 8px 10px; text-align: left; vertical-align: top; min-width: 130px; max-width: 260px; white-space: normal; overflow-wrap: anywhere; background-clip: padding-box; }
.fsd-content th:first-child, .fsd-content td:first-child { position: sticky; left: 0; min-width: 145px; box-shadow: 2px 0 0 #e2e8f0; }
.fsd-content th { background: #f1f5f9 !important; font-weight: 750; color: var(--crs-navy); border-bottom: 1px solid #cbd5e1; z-index: 3; }
.fsd-content thead th:first-child { background: #eaf1fb !important; z-index: 5; }
.fsd-content tbody td:first-child { background: #ffffff; z-index: 2; font-weight: 650; color: #1e293b; }
.fsd-content tr:nth-child(even) td { background: #f8fafc; }
.fsd-content tr:nth-child(even) td:first-child { background: #f8fafc; }
.fsd-content h1, .fsd-content h2 { color: var(--crs-navy); margin-top: 20px; }
.fsd-content h3 { color: var(--crs-indigo-dark); margin-top: 17px; }
.fsd-content blockquote { border-left: 4px solid #f59e0b; background: #fffbeb; margin: 10px 0; padding: 8px 16px; color: #78350f; border-radius: 4px; }
.fsd-content code { background: #f1f5f9; padding: 2px 5px; border-radius: 3px; font-size: 12px; }
.fsd-content ul, .fsd-content ol { padding-left: 22px; }
.fsd-content li { margin: 5px 0; }
.output-panel .prose { font-size: 14px; line-height: 1.7; }
.attribution { font-size: 12px; color: #64748b; margin: 8px 0; }
.evidence-intro {
    background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 9px;
    padding: 10px 13px; color: #1e3a8a; font-size: 12.5px; margin-bottom: 10px;
}
.contact-line {
    margin: 8px 2px 0; font-size: 12.5px; line-height: 1.35; color: #64748b; text-align: center;
}
.contact-line a { color: var(--crs-indigo-dark); text-decoration: none; font-weight: 700; }
.contact-line a:hover { text-decoration: underline; }
.footer { display: none; }
.footer a { color: var(--crs-indigo-dark); text-decoration: none; font-weight: 650; }
.helper-table { font-size: 13px; }
.advisor-result {
    background: #f0fdf4; border: 1px solid #86efac; border-radius: 7px;
    padding: 10px 14px; font-size: 13px; color: #166534; margin-top: 8px;
}
@media (max-width: 900px) {
    html, body { width: 100%; max-width: 100%; overflow-x: hidden; }
    .gradio-container {
        width: 100% !important; max-width: 100% !important; min-width: 0 !important;
        padding: 12px !important; box-sizing: border-box !important; overflow-x: hidden;
    }
    .crs-header { display: block !important; align-items: flex-start; }
    .crs-header > div {
        width: 100% !important; max-width: 100% !important; min-width: 0 !important;
        box-sizing: border-box !important;
    }
    .header-login { margin-top: 10px; justify-content: flex-start; }
    .crs-header h1 { font-size: 28px; }
    .disclaimer-banner { width: 100%; max-width: 100%; box-sizing: border-box; }
    #workspace-grid {
        display: flex !important; flex-direction: column !important;
        width: 100% !important; max-width: 100% !important; min-width: 0 !important;
    }
    #input-wizard, #results-workspace {
        width: 100% !important; max-width: 100% !important; min-width: 0 !important;
        flex: 0 0 auto !important; box-sizing: border-box !important;
    }
    #input-wizard { position: static; max-height: none; overflow: visible; padding-right: 0; }
    #results-workspace { min-height: 500px; margin-top: 14px; padding: 12px; overflow-x: hidden; }
    .step-card, .status-card, .result-groups { min-width: 0 !important; max-width: 100% !important; }
    #generate-action { position: static; background: transparent; }
    .jurisdiction-meta { grid-template-columns: 1fr; }
    .result-groups button { font-size: 12px !important; padding: 8px !important; }
    .table-scroll { max-width: calc(100vw - 42px); }
    .fsd-content table { min-width: 940px; font-size: 12px; }
}

"""

# ---------------------------------------------------------------------------
# Helper: format KB for display (sources panel + staleness)
# ---------------------------------------------------------------------------
def show_kb(jurisdiction: str) -> str:
    if not jurisdiction:
        return ""
    kb = load_kb(jurisdiction)
    if not kb:
        return "No knowledge base entry found for this jurisdiction."

    meta = kb.get("_meta", {})
    last_updated = meta.get("last_updated", "Unknown")
    confidence = meta.get("confidence", "Unknown")
    gaps = meta.get("gaps", [])
    sources = meta.get("sources", [])

    staleness_days = 0
    try:
        updated = datetime.date.fromisoformat(last_updated)
        staleness_days = (datetime.date.today() - updated).days
    except Exception:
        pass

    lines = []

    if staleness_days > STALENESS_WARN_DAYS:
        lines += [
            "> [!WARNING]",
            "> **KB Staleness:** Data is " + str(staleness_days) + " days old "
            "(threshold: " + str(STALENESS_WARN_DAYS) + " days). "
            "Review [INFERRED] flags carefully and verify with official sources.",
            "",
        ]

    lines += [
        "## Knowledge Base: " + kb.get("country", jurisdiction),
        "",
        "**Confidence:** " + confidence
        + "  |  **Last Updated:** " + last_updated
        + "  |  **Age:** " + str(staleness_days) + " days",
        "",
        "**Authority:** " + kb.get("authority", "N/A"),
        "**Legal Basis:** " + kb.get("legal_basis", "N/A"),
        "**CRS Status:** " + kb.get("crs_status", "N/A"),
        "**Reporting Deadline:** " + kb.get("reporting_deadline", "N/A"),
        "**Submission Channel:** " + kb.get("submission_method", "N/A"),
        "**XML Schema:** " + kb.get("xml_schema", "N/A"),
        "**Portal:** " + kb.get("portal_name", "N/A") + " - " + kb.get("portal_url", ""),
        "**Nil Report Required:** " + kb.get("nil_report_required", "N/A"),
        "**Data Retention:** " + str(kb.get("data_retention_years", "N/A")) + " years",
        "",
        "### Thresholds",
    ]
    for k, v in kb.get("thresholds", {}).items():
        lines.append("- " + k.replace("_", " ").title() + ": " + str(v))

    lines += ["", "### Key Dates"]
    for k, v in kb.get("key_dates", {}).items():
        lines.append("- " + k.replace("_", " ").title() + ": " + str(v))

    lines += ["", "### Penalties"]
    for k, v in kb.get("penalties", {}).items():
        lines.append("- " + k.replace("_", " ").title() + ": " + str(v))

    lines += ["", "### Local-Specific Rules"]
    for note in kb.get("local_specific_rules", []):
        lines.append("- " + note)

    fatca = kb.get("fatca", {})
    if fatca:
        lines += [
            "",
            "### FATCA",
            "**IGA Type:** " + fatca.get("iga_type", "N/A"),
            "**Signed:** " + fatca.get("iga_signed", "N/A"),
            "**Portal:** " + fatca.get("portal", "N/A"),
        ]

    if sources:
        lines += ["", "### Data Sources"]
        for s in sources:
            url = s.get("url", "")
            fetched = s.get("fetched_at", "unknown")
            notes = s.get("notes", "")
            note_str = ("  - " + notes) if notes else ""
            lines.append("- [" + url + "](" + url + ") *(fetched " + fetched + ")*" + note_str)

    if gaps:
        lines += ["", "### Known Gaps / Items to Verify"]
        for g in gaps:
            lines.append("- " + g)

    lines += [
        "",
        "---",
        "*This knowledge base was compiled from official government sources. "
        "Fields marked [INFERRED] were not confirmed at fetch time.*",
    ]
    return "\n".join(lines)


def jurisdiction_info_html(jurisdiction: str) -> str:
    """Compact, review-oriented jurisdiction profile shown beside the selector."""
    import html
    if not jurisdiction:
        return '<div class="jurisdiction-card">Select a reporting jurisdiction to inspect coverage.</div>'

    kb = load_kb(jurisdiction)
    meta = kb.get("_meta", {}) if kb else {}
    confidence = str(meta.get("confidence", "Unknown"))
    gaps = meta.get("gaps", []) or []
    sources = meta.get("sources", []) or []
    registry = kb.get("_source_registry", {}) if isinstance(kb.get("_source_registry"), dict) else {}
    freshness = freshness_from_registry(registry)
    core_fields = [
        kb.get("authority"), kb.get("reporting_deadline"), kb.get("xml_schema"),
        kb.get("submission_method"), kb.get("nil_report_required"),
        kb.get("key_dates"), kb.get("thresholds"),
    ] if kb else []
    covered = sum(1 for value in core_fields if value not in (None, "", [], {}))
    enriched = jurisdiction in ENRICHED_JURISDICTIONS
    review_required = "Yes" if gaps or confidence.lower() != "high" else "Before production"
    marker = "\u2605 " if enriched else ""
    source_count = len(sources) or len(registry.get("sources", []) or [])

    return (
        '<div class="jurisdiction-card">'
        '<strong>' + marker + html.escape(jurisdiction) + '</strong>'
        '<div class="jurisdiction-meta">'
        '<span><b>Coverage:</b> ' + str(covered) + '/7 core fields</span>'
        '<span><b>Confidence:</b> ' + html.escape(confidence) + '</span>'
        '<span><b>KB freshness:</b> ' + html.escape(freshness["status"]) + '</span>'
        '<span><b>Last verified:</b> ' + html.escape(freshness["last_verified"]) + '</span>'
        '<span><b>Official sources:</b> ' + str(source_count) + '</span>'
        '<span><b>Refresh mode:</b> Curated KB</span>'
        '<span><b>Review:</b> ' + review_required + '</span>'
        '</div></div>'
    )

def required_step_status(value) -> str:
    if value:
        return '<span class="step-complete">\u2713 Complete</span>'
    return '<span class="step-required">Required</span>'


def required_step_heading(number: int, title: str, value) -> str:
    return (
        '<div class="step-heading"><span><span class="step-number">' + str(number) + '</span>'
        '<span class="step-title">' + title + '</span></span>'
        + required_step_status(value) + '</div>'
    )


# ---------------------------------------------------------------------------
# Helper: KB coverage / hallucination guard
# ---------------------------------------------------------------------------
def build_kb_coverage(kb: dict, attribution: str, source_note: str, inferred_count: int = 0) -> str:
    if not kb:
        return "*No KB data available for this jurisdiction. All content is LLM-estimated - review carefully.*"

    key_facts = {
        "Authority": (kb.get("authority"), "Summary, Governance"),
        "Reporting Deadline": (kb.get("reporting_deadline"), "Summary, Governance"),
        "XML Schema": (kb.get("xml_schema"), "Downstream"),
        "Submission Method": (kb.get("submission_method"), "Downstream"),
        "High Value Threshold": (
            kb.get("thresholds", {}).get("pre_existing_individual_high_value"), "Summary, Field Catalog"
        ),
        "Entity Review Threshold": (
            kb.get("thresholds", {}).get("pre_existing_entity_review_trigger"), "Summary, Field Catalog"
        ),
        "Account Snapshot Date": (
            kb.get("key_dates", {}).get("account_balance_snapshot"), "Downstream, Governance"
        ),
    }

    present = sum(1 for v, _ in key_facts.values() if v)
    total = len(key_facts)
    pct = int(100 * present / total)
    confidence = kb.get("_meta", {}).get("confidence", "Unknown")
    level = "High" if pct >= 85 else "Medium" if pct >= 50 else "Low"

    rows = ["| Field | KB Value | Verify In |", "|---|---|---|"]
    for field, (value, where) in key_facts.items():
        display = str(value) if value else "*Not in KB - LLM estimated*"
        rows.append("| " + field + " | " + display + " | " + where + " |")

    inferred_note = ""
    if inferred_count > 0:
        inferred_note = (
            "\n\n**[INFERRED] Tags in FSD: " + str(inferred_count) + "** - "
            "These facts were not confirmed in the knowledge base. "
            "Verify each one before implementation."
        )

    registry = kb.get("_source_registry", {}) if isinstance(kb.get("_source_registry"), dict) else {}
    freshness = freshness_from_registry(registry)
    freshness_note = (
        "**Source freshness:** " + freshness["status"]
        + " | Last verified: " + freshness["last_verified"]
        + " | Refresh mode: curated KB, no runtime fact rewrite."
    )

    lines = (
        [
            "**KB Coverage: " + str(present) + "/" + str(total)
            + " key fields (" + str(pct) + "%) "
            + "| KB Confidence: " + confidence
            + " | FSD Grounding: " + level + "**",
            "",
            freshness_note,
            "",
            "Verify KB-sourced facts against the generated FSD. Flag any discrepancies.",
            "",
        ]
        + rows
        + [
            "",
            inferred_note,
            "*" + attribution + "  |  source: " + source_note + "*",
        ]
    )
    return "\n".join(lines)

# ---------------------------------------------------------------------------
# Entity type advisor
# ---------------------------------------------------------------------------
def suggest_fi_type(q1, q2, q3, q4, q5):
    answered = [v for v in [q1, q2, q3, q5] if v is not None]
    if not answered:
        return ""

    if q1 == "Yes":
        label = "Depository Institution"
        reason = "You accept customer deposits. Banks, building societies, and credit unions fall in this category."
    elif q5 == "Yes":
        label = "Specified Insurance Company"
        reason = "You issue life insurance or annuity contracts with a cash surrender value."
    elif q3 == "Yes":
        if q4 == "Yes":
            label = "Investment Entity (Type A) - Managed by another FI"
            reason = "Your fund or investment vehicle is managed day-to-day by another regulated financial institution."
        elif q4 == "No":
            label = "Investment Entity (Type B) - Other"
            reason = "Your fund or trust is not managed by another regulated FI. Self-managed funds and most trusts fall here."
        else:
            return "You indicated you are a fund or investment vehicle. Answer question 4 to refine the suggestion."
    elif q2 == "Yes":
        label = "Custodial Institution"
        reason = "You hold financial assets on behalf of customers. Brokers, prime brokers, and asset managers fall here."
    elif len(answered) >= 3 and all(v == "No" for v in answered):
        label = "Non-Reporting Financial Institution"
        reason = (
            "You may qualify as Non-Reporting. This covers government bodies, central banks, pension funds, "
            "and certain exempt vehicles. Verify against your local authority's exempt entity list."
        )
    else:
        return "Answer more questions above to narrow down your institution type."

    return (
        "**Suggested: " + label + "**\n\n"
        + reason
        + "\n\n*Click Apply to auto-select, or use the dropdown to override.*"
    )


def apply_fi_type(suggestion):
    if not suggestion:
        return gr.update()
    for label in FI_LABELS:
        if label in suggestion:
            return gr.update(value=label)
    return gr.update()


# ---------------------------------------------------------------------------
# Core generation function
# ---------------------------------------------------------------------------
def run_generation(
    fi_type, jurisdiction, upstream_sources,
    account_types, reporting_year, de_minimis, group_fi,
    use_latest, req_doc, fatca_toggle,
    anon_count,
    profile: gr.OAuthProfile | None = None,
    progress=gr.Progress(track_tqdm=True),
):
    # 16 outputs: status, quality panel, 8 Blueprint sections, fatca, DOCX download, XLSX download, attribution, live_fetch, anon_state
    DEFAULT_QUALITY_HTML = (
        '<div class="quality-panel"><div class="quality-panel-title">Generation diagnostics</div><div class="quality-row"><span>•</span><b>Not run</b><small>Generate a blueprint to run technical checks.</small></div></div>'
    )
    EMPTY_REST = (
        DEFAULT_QUALITY_HTML,
        "", "", "", "", "", "", "", "",
        FATCA_PLACEHOLDER_HTML,
        gr.update(visible=False), gr.update(visible=False), "", "", anon_count
    )

    def _err(msg: str):
        err_html = md_to_html(msg)
        return (msg, DEFAULT_QUALITY_HTML) + (err_html,) + ("",) * 7 + (FATCA_PLACEHOLDER_HTML,) + (gr.update(visible=False), gr.update(visible=False), "", "", anon_count)

    if not fi_type or fi_type not in FI_MAP:
        return ("Please select your institution type to continue.",) + EMPTY_REST

    if not jurisdiction:
        return ("Please select a jurisdiction to continue.",) + EMPTY_REST

    allowed, limit_msg = check_rate_limit(anon_count, profile)
    if not allowed:
        return (limit_msg, DEFAULT_QUALITY_HTML) + (md_to_html(limit_msg),) + ("",) * 7 + (FATCA_PLACEHOLDER_HTML,) + (gr.update(visible=False), gr.update(visible=False), "", "", anon_count)

    try:

        if not upstream_sources:
            upstream_sources = ["Core Banking System", "Manual / Spreadsheets"]
        if not account_types:
            account_types = ["Individual accounts", "Entity accounts"]

        user_doc_text = None
        req_doc_status = ""
        if req_doc is not None:
            file_path = req_doc if isinstance(req_doc, str) else getattr(req_doc, "name", None)
            if file_path:
                user_doc_text, req_doc_status = parse_uploaded_doc(file_path)

        params = {
            "fi_type": fi_type,
            "jurisdiction": jurisdiction,
            "upstream_sources": upstream_sources,
            "account_types": account_types,
            "reporting_year": int(reporting_year) if reporting_year else 2024,
            "de_minimis": bool(de_minimis),
            "group_fi": bool(group_fi),
            "fatca_toggle": bool(fatca_toggle),
        }
        cache_key = jurisdiction + "_" + fi_type + ("_fatca" if fatca_toggle else "")

        if not use_latest and not user_doc_text:
            cached = get_cache(cache_key)
            if cached and cached.get("summary"):
                age = cache_age_label(cache_key)
                kb = load_kb(jurisdiction)
                coverage_md = build_kb_coverage(
                    kb, cached.get("attribution", ""), "knowledge base cache",
                    cached.get("inferred_count", 0)
                )
                cached_quality = cached.get("_quality_gate") or {}
                cached_quality_html = quality_gate_html(cached_quality) if cached_quality else DEFAULT_QUALITY_HTML
                docx_update_cached = gr.update(visible=False)
                xlsx_update_cached = gr.update(visible=False)
                if not cached_quality or cached_quality.get("passed"):
                    docx_path = build_docx(cached, params)
                    xlsx_path = build_xlsx(cached, params)
                    docx_update_cached = gr.update(value=docx_path, visible=True)
                    xlsx_update_cached = gr.update(value=xlsx_path, visible=True)
                new_anon = increment_usage(anon_count, profile)
                _fatca_cached = cached.get("fatca", "")
                evidence_cached = cached.get("evidence", "")
                return (
                    "Blueprint loaded from knowledge base cache (" + age + ").",
                    cached_quality_html,
                    md_to_html(cached.get("summary", "")),
                    md_to_html(cached.get("architecture", "")),
                    md_to_html(cached.get("field_catalog", "")),
                    md_to_html(cached.get("downstream", "")),
                    md_to_html(cached.get("risk_flags", "")),
                    md_to_html(cached.get("classification", "")),
                    md_to_html(cached.get("governance", "")),
                    md_to_html(cached.get("testing", "")),
                    md_to_html(_fatca_cached) if _fatca_cached else FATCA_PLACEHOLDER_HTML,
                    docx_update_cached,
                    xlsx_update_cached,
                    coverage_md + ("\n\n" + evidence_cached if evidence_cached else ""),
                    "",
                    new_anon,
                )

        live_text = None
        live_fetch_display = ""

        if use_latest:
            if progress is not None:
                progress(0.05, desc="Fetching latest guidance from source...")
            live_text, fetch_status = fetch_latest_guidance(jurisdiction, JURISDICTION_URLS)
            if live_text:
                preview = live_text[:3000]
                live_fetch_display = "\n".join([
                    "### Live Guidance Fetched",
                    "",
                    "**Source:** " + fetch_status,
                    "",
                    "**Preview (first 3,000 chars):**",
                    "",
                    "```",
                    preview,
                    "```",
                    "",
                    "*Full text (up to 5,000 chars) injected into LLM prompt alongside the knowledge base.*",
                ])
            else:
                if progress is not None:
                    progress(0.1, desc=fetch_status)
                live_fetch_display = "\n".join([
                    "### Live guidance status",
                    "",
                    "**Status:** Not available",
                    "",
                    "**Fallback used:** Curated jurisdiction knowledge base",
                    "",
                    "**Action:** Verify current local authority guidance before implementation.",
                    "",
                    "**Technical detail:** " + fetch_status,
                ])

        if user_doc_text:
            if progress is not None:
                progress(0.1, desc="Requirements document parsed: " + req_doc_status)

        if progress is not None:
            progress(0.15, desc="Generating Blueprint...")

        result = generate_fsd(params, live_text, progress, user_doc_text)

        kb = load_kb(jurisdiction)
        source_note = "live guidance" if (use_latest and live_text) else "knowledge base"
        if user_doc_text:
            source_note = source_note + " + uploaded requirements doc"

        coverage_md = build_kb_coverage(
            kb, result.get("attribution", ""), source_note,
            result.get("inferred_count", 0)
        )

        if result.get("summary") and "unavailable" not in result["summary"].lower():
            if not use_latest and not user_doc_text:
                set_cache(cache_key, result)

        quality = result.get("_quality_gate") or {}
        quality_panel_html = quality_gate_html(quality) if quality else DEFAULT_QUALITY_HTML
        docx_update = gr.update(visible=False)
        xlsx_update = gr.update(visible=False)
        status_text = result.get("status", "Blueprint generated.")
        if result.get("summary"):
            if quality.get("passed", False):
                docx_path = build_docx(result, params)
                xlsx_path = build_xlsx(result, params)
                docx_update = gr.update(value=docx_path, visible=True)
                xlsx_update = gr.update(value=xlsx_path, visible=True)
            else:
                status_text = (
                    "Blueprint generated, but downloads are blocked because internal generation checks failed. "
                    "Open Generation diagnostics and regenerate."
                )

        if progress is not None:
            progress(1.0, desc="Quality checks complete." if quality else "Done.")

        new_anon = increment_usage(anon_count, profile)

        _fatca_out = result.get("fatca", "")
        evidence_md = result.get("evidence", "")
        review_count = result.get("local_confirmation_count", 0)
        if review_count:
            status_text += " " + str(review_count) + " verification items captured."
        return (
            status_text,
            quality_panel_html,
            md_to_html(result.get("summary", "")),
            md_to_html(result.get("architecture", "")),
            md_to_html(result.get("field_catalog", "")),
            md_to_html(result.get("downstream", "")),
            md_to_html(result.get("risk_flags", "")),
            md_to_html(result.get("classification", "")),
            md_to_html(result.get("governance", "")),
            md_to_html(result.get("testing", "")),
            md_to_html(_fatca_out) if _fatca_out else FATCA_PLACEHOLDER_HTML,
            docx_update,
            xlsx_update,
            coverage_md + ("\n\n" + evidence_md if evidence_md else ""),
            live_fetch_display,
            new_anon,
        )

    except Exception as exc:
        import traceback
        err_detail = str(exc)
        msg = (
            "Something went wrong generating your Blueprint. Please try again.\n\n"
            "If the issue persists, [contact Abhinit Sen on LinkedIn](" + LINKEDIN_URL + ")."
        )
        return _err(msg)


def update_fi_helper(fi_type):
    if not fi_type or fi_type not in FI_MAP:
        return ""
    ft = FI_MAP[fi_type]
    return (
        "**" + ft["label"] + "**\n\n"
        + ft["description"] + "\n\n"
        + "*Examples:* " + ft["examples"] + "\n\n"
        + "*Key CRS obligation:* " + ft["key_obligations"]
    )


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
with gr.Blocks(theme=gr.themes.Soft(primary_hue="blue", neutral_hue="slate"), css=CSS, title="CRS Blueprint") as demo:

    anon_count_state = gr.State(value=0)

    with gr.Row(elem_classes=["crs-header"]):
        with gr.Column(scale=8):
            gr.HTML("""
            <div>
                <h1>CRS Blueprint</h1>
                <p class="promise">Turn CRS obligations into implementation-ready requirements.</p>
                <p class="descriptor">A structured starting point for data mapping, transformation rules, controls, testing and your CRS Functional Specification Document.</p>
            </div>
            """)
        with gr.Column(scale=2, min_width=180, elem_classes=["header-login"]):
            login_btn = gr.LoginButton(size="sm")

    gr.HTML("""
    <div class="disclaimer-banner">
        <strong>Important</strong>
        This Blueprint is an implementation starting point. Verify jurisdiction-specific requirements against official guidance before use.
    </div>
    """)

    with gr.Row(equal_height=False, elem_id="workspace-grid"):

        with gr.Column(scale=4, min_width=360, elem_id="input-wizard"):

            with gr.Group(elem_classes=["step-card"]):
                fi_step_header = gr.HTML(
                    '<div class="step-heading"><span><span class="step-number">1</span>'
                    '<span class="step-title">Institution</span></span>'
                    '<span class="step-required">Required</span></div>'
                )
                fi_type = gr.Dropdown(
                    choices=FI_LABELS,
                    label="Institution type",
                    value=None,
                    allow_custom_value=False,
                    info="Select the category that best describes your organisation.",
                )
                with gr.Accordion("Not sure which type? Use the classifier", open=False):
                    gr.Markdown("Answer these questions and we will suggest your type:")
                    adv_q1 = gr.Radio(choices=["Yes", "No"], label="1. Do you accept customer deposits?", value=None)
                    adv_q2 = gr.Radio(choices=["Yes", "No"], label="2. Do you hold financial assets for customers?", value=None)
                    adv_q3 = gr.Radio(choices=["Yes", "No"], label="3. Are you a fund, trust or investment vehicle?", value=None)
                    adv_q4 = gr.Radio(choices=["Yes", "No"], label="4. Is the vehicle managed by another regulated FI?", value=None)
                    adv_q5 = gr.Radio(choices=["Yes", "No"], label="5. Do you issue cash-value insurance or annuity contracts?", value=None)
                    adv_suggestion = gr.Markdown(value="", elem_classes=["advisor-result"])
                    adv_apply_btn = gr.Button("Apply suggested type", size="sm", variant="secondary")
                fi_helper_md = gr.Markdown(value="", elem_classes=["helper-table"])

            with gr.Group(elem_classes=["step-card"]):
                jurisdiction_step_header = gr.HTML(
                    '<div class="step-heading"><span><span class="step-number">2</span>'
                    '<span class="step-title">Jurisdiction</span></span>'
                    '<span class="step-complete">&#10003; Complete</span></div>'
                )
                gr.HTML('<div class="enriched-legend">&#9733; Enriched jurisdictions include enhanced local CRS, FATCA, TIN and submission guidance.</div>')
                jurisdiction = gr.Dropdown(
                    choices=JURISDICTION_LIST,
                    label="Reporting jurisdiction",
                    value="United Kingdom",
                    info="The jurisdiction receiving the CRS submission.",
                )
                jurisdiction_info = gr.HTML(value=jurisdiction_info_html("United Kingdom"))
                use_latest = gr.Checkbox(
                    label="Experimental: check latest authority guidance",
                    value=False,
                    info="Best-effort only. Generation continues from the curated knowledge base if the authority website is unavailable.",
                )

            with gr.Group(elem_classes=["step-card"]):
                sources_step_header = gr.HTML(
                    '<div class="step-heading"><span><span class="step-number">3</span>'
                    '<span class="step-title">Data sources</span></span>'
                    '<span class="step-complete">&#10003; Complete</span></div>'
                )
                upstream_sources = gr.CheckboxGroup(
                    choices=UPSTREAM_CHOICES,
                    label="Where does your account data live?",
                    value=["Core Banking System"],
                    info="Select all that apply.",
                    elem_classes=["source-selector"],
                )
                gr.HTML("""
                <div class="source-guide">
                    <b>Core/wealth/trading:</b> accounts, balances, positions, income &nbsp;·&nbsp;
                    <b>CRM/KYC/CLM:</b> identity, tax residence, TIN, self-certification<br>
                    <b>Custody/fund admin/corporate actions:</b> holdings, dividends, proceeds &nbsp;·&nbsp;
                    <b>GL/warehouse/manual/vendor:</b> controls, lineage, remediation and reference data
                </div>
                """)

            with gr.Group(elem_classes=["step-card"]):
                gr.HTML(
                    '<div class="step-heading"><span><span class="step-number">4</span>'
                    '<span class="step-title">Scope</span></span>'
                    '<span class="step-optional">Configured</span></div>'
                )
                with gr.Accordion("Review scope and advanced options", open=False):
                    account_types = gr.CheckboxGroup(
                        choices=["Individual accounts", "Entity accounts"],
                        label="Account types in scope",
                        value=["Individual accounts", "Entity accounts"],
                    )
                    reporting_year = gr.Number(
                        label="Reporting year", value=2024, precision=0, minimum=2016, maximum=2030,
                    )
                    de_minimis = gr.Checkbox(
                        label="De minimis threshold applicable", value=False,
                        info="Applies only where the relevant rules permit the threshold.",
                    )
                    group_fi = gr.Checkbox(label="Part of a Group FI structure", value=False)
                    fatca_toggle = gr.Checkbox(
                        label="Include FATCA crosswalk section", value=True,
                        info="Adds IGA model, CRS/FATCA differences, workflow and US-indicia considerations.",
                    )

            with gr.Group(elem_classes=["step-card"]):
                gr.HTML(
                    '<div class="step-heading"><span><span class="step-number">5</span>'
                    '<span class="step-title">Requirements document</span></span>'
                    '<span class="step-optional">Optional</span></div>'
                )
                req_doc = gr.File(
                    label="Add internal requirements or policy context",
                    file_types=[".pdf", ".docx", ".txt"],
                    type="filepath",
                    elem_id="requirements-upload",
                )

            with gr.Group(elem_id="generate-action"):
                gr.HTML(
                    '<div class="step-heading"><span><span class="step-number">6</span>'
                    '<span class="step-title">Generate</span></span></div>'
                )
                generate_btn = gr.Button(
                    "Generate Blueprint", variant="primary", size="lg", elem_id="generate-btn",
                )
                gr.HTML('<div class="contact-line">CRS Blueprint &middot; Contact <a href="' + LINKEDIN_URL + '" target="_blank" rel="noopener noreferrer">Abhinit Sen</a> for custom requirements</div>')

        with gr.Column(scale=8, min_width=620, elem_classes=["output-panel"], elem_id="results-workspace"):
            gr.HTML("""
            <div class="result-header">
                <div>
                    <h2>Blueprint workspace</h2>
                    <p>Your implementation requirements, evidence and review items will appear here.</p>
                </div>
            </div>
            """)
            status_msg = gr.Markdown(
                value="**Ready.** Complete the required inputs, then generate your Blueprint.",
                elem_classes=["status-card"],
            )
            with gr.Accordion("Generation diagnostics", open=False):
                quality_panel = gr.HTML(
                    value='<div class="quality-panel"><div class="quality-panel-title">Generation diagnostics</div><div class="quality-row"><span>•</span><b>Not run</b><small>Generate a blueprint to run technical checks.</small></div></div>'
                )
            with gr.Row(elem_classes=["result-actions"]):
                download_btn = gr.DownloadButton(
                    label="Download Blueprint (.docx)", visible=False, variant="primary",
                )
                xlsx_download_btn = gr.DownloadButton(
                    label="Download Implementation Workbook (.xlsx)", visible=False,
                )
            with gr.Tabs(elem_classes=["result-groups"]):
                with gr.Tab("Overview"):
                    summary_out = gr.HTML(value="")
                with gr.Tab("Data & Architecture"):
                    with gr.Tabs(elem_classes=["nested-tabs"]):
                        with gr.Tab("Architecture"):
                            architecture_out = gr.HTML(value="")
                        with gr.Tab("Field Catalogue"):
                            field_catalog_out = gr.HTML(value="")
                        with gr.Tab("Downstream"):
                            downstream_out = gr.HTML(value="")
                with gr.Tab("Compliance Rules"):
                    with gr.Tabs(elem_classes=["nested-tabs"]):
                        with gr.Tab("Risk & Audit"):
                            risk_out = gr.HTML(value="")
                        with gr.Tab("Classification"):
                            classification_out = gr.HTML(value="")
                        with gr.Tab("FATCA"):
                            fatca_out = gr.HTML(value=FATCA_PLACEHOLDER_HTML)
                with gr.Tab("Controls & Testing"):
                    with gr.Tabs(elem_classes=["nested-tabs"]):
                        with gr.Tab("Governance"):
                            governance_out = gr.HTML(value="")
                        with gr.Tab("Testing"):
                            testing_out = gr.HTML(value="")
                with gr.Tab("Evidence & Assumptions"):
                    gr.HTML(
                        '<div class="evidence-intro"><b>Review basis:</b> use evidence labels and verification tasks to separate verified facts, user inputs, implementation hints and items that need checking before build lock.</div>'
                    )
                    attribution_md = gr.Markdown(value="", elem_classes=["attribution"])
                    with gr.Tabs(elem_classes=["nested-tabs"]):
                        with gr.Tab("Knowledge base"):
                            kb_viewer_md = gr.Markdown(value="Select a jurisdiction to view its knowledge base.")
                        with gr.Tab("Live guidance"):
                            live_fetch_md = gr.Markdown(
                                value="**Status:** Not requested. Enable the experimental live-guidance check before generation if required."
                            )

    # ---------------------------------------------------------------------------
    # Event wiring
    # ---------------------------------------------------------------------------
    fi_type.change(fn=update_fi_helper, inputs=fi_type, outputs=fi_helper_md)
    fi_type.change(
        fn=lambda value: required_step_heading(1, "Institution", value),
        inputs=fi_type,
        outputs=fi_step_header,
    )

    jurisdiction.change(fn=show_kb, inputs=jurisdiction, outputs=kb_viewer_md)
    jurisdiction.change(fn=jurisdiction_info_html, inputs=jurisdiction, outputs=jurisdiction_info)
    jurisdiction.change(
        fn=lambda value: required_step_heading(2, "Jurisdiction", value),
        inputs=jurisdiction,
        outputs=jurisdiction_step_header,
    )
    upstream_sources.change(
        fn=lambda value: required_step_heading(3, "Data sources", value),
        inputs=upstream_sources,
        outputs=sources_step_header,
    )
    demo.load(fn=show_kb, inputs=jurisdiction, outputs=kb_viewer_md)
    demo.load(fn=jurisdiction_info_html, inputs=jurisdiction, outputs=jurisdiction_info)

    for q in [adv_q1, adv_q2, adv_q3, adv_q4, adv_q5]:
        q.change(
            fn=suggest_fi_type,
            inputs=[adv_q1, adv_q2, adv_q3, adv_q4, adv_q5],
            outputs=adv_suggestion,
        )

    adv_apply_btn.click(fn=apply_fi_type, inputs=adv_suggestion, outputs=fi_type)

    generate_btn.click(
        fn=run_generation,
        inputs=[
            fi_type, jurisdiction, upstream_sources,
            account_types, reporting_year, de_minimis, group_fi,
            use_latest, req_doc, fatca_toggle,
            anon_count_state,
        ],
        outputs=[
            status_msg,
            quality_panel,
            summary_out, architecture_out, field_catalog_out,
            downstream_out,
            risk_out,
            classification_out, governance_out, testing_out,
            fatca_out,
            download_btn,
            xlsx_download_btn,
            attribution_md,
            live_fetch_md,
            anon_count_state,
        ],
    )

if __name__ == "__main__":
    demo.launch()
