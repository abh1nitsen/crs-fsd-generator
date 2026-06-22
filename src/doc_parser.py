"""Parse uploaded requirement documents: PDF, DOCX, or plain text."""
from pathlib import Path

MAX_CHARS = 8000


def parse_uploaded_doc(file_path: str) -> tuple[str, str]:
    """
    Returns (extracted_text, status_message).
    extracted_text is empty string on failure.
    """
    if not file_path:
        return "", "No file provided."

    path = Path(file_path)
    suffix = path.suffix.lower()

    try:
        if suffix == ".txt":
            text = path.read_text(encoding="utf-8", errors="replace")
            return text[:MAX_CHARS], f"Parsed text file: {len(text):,} chars."

        elif suffix == ".pdf":
            try:
                import pdfplumber, io
                with pdfplumber.open(str(path)) as pdf:
                    pages = [p.extract_text() or "" for p in pdf.pages[:20]]
                text = "\n".join(pages).strip()
                return text[:MAX_CHARS], f"Parsed PDF: {len(pdf.pages)} pages, {len(text):,} chars."
            except Exception as e:
                return "", f"PDF parse failed: {e}"

        elif suffix in (".docx", ".doc"):
            try:
                from docx import Document
                doc = Document(str(path))
                paras = [p.text for p in doc.paragraphs if p.text.strip()]
                text = "\n".join(paras)
                return text[:MAX_CHARS], f"Parsed Word doc: {len(paras)} paragraphs, {len(text):,} chars."
            except Exception as e:
                return "", f"DOCX parse failed: {e}"

        else:
            text = path.read_text(encoding="utf-8", errors="replace")
            return text[:MAX_CHARS], f"Parsed as text: {len(text):,} chars."

    except Exception as e:
        return "", f"Document parsing failed: {e}"
