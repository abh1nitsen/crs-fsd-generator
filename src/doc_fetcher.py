"""Live document fetcher with 3-retry logic and fallback signalling."""
import time
import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "CRS-FSD-Generator/1.0 (compliance tool; contact: https://www.linkedin.com/in/abhinit-sen-63443015/)"}
TIMEOUT = 12
MAX_CHARS = 12000


def _fetch_url(url: str) -> str | None:
    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    ct = resp.headers.get("content-type", "")
    if "pdf" in ct:
        return _extract_pdf(resp.content)
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    return text[:MAX_CHARS] if text else None


def _extract_pdf(content: bytes) -> str | None:
    try:
        import pdfplumber, io
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            pages = [p.extract_text() or "" for p in pdf.pages[:15]]
        text = "\n".join(pages).strip()
        return text[:MAX_CHARS] if text else None
    except Exception:
        return None


def fetch_latest_guidance(jurisdiction: str, url_map: dict) -> tuple[str | None, str]:
    """
    Returns (text_content, status_message).
    text_content is None if all attempts fail.
    """
    entry = url_map.get(jurisdiction, {})
    urls = [u for u in [entry.get("local_url"), entry.get("oecd_url")] if u]

    if not urls:
        return None, "No source URL found for this jurisdiction. Using knowledge base."

    for url in urls:
        for attempt in range(1, 4):
            try:
                text = _fetch_url(url)
                if text and len(text) > 300:
                    return text, f"Live guidance fetched from {url}"
            except Exception:
                pass
            if attempt < 3:
                time.sleep(attempt * 2)

    return None, "The official source could not be fetched. The curated jurisdiction knowledge base remains available."
