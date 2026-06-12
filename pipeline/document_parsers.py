"""Text extraction from uploaded document files, one parser per format.

Each parser takes raw bytes and returns extracted text. ``parse_document``
dispatches on file extension; unsupported or unparsable files raise
``DocumentParseError`` with a user-facing message.
"""

from __future__ import annotations

import csv
import io
import json


class DocumentParseError(Exception):
    """Raised when a document cannot be parsed; message is user-facing."""


def _decode(data: bytes) -> str:
    return data.decode("utf-8", errors="ignore")


def _parse_text(data: bytes) -> str:
    return _decode(data)


def _parse_pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _parse_docx(data: bytes) -> str:
    from docx import Document

    doc = Document(io.BytesIO(data))
    return "\n".join(para.text for para in doc.paragraphs)


def _parse_html(data: bytes) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(_decode(data), "html.parser")
    for tag in soup(["script", "style", "nav", "noscript"]):
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)


def _parse_pptx(data: bytes) -> str:
    from pptx import Presentation

    prs = Presentation(io.BytesIO(data))
    parts: list[str] = []
    for i, slide in enumerate(prs.slides, start=1):
        texts = [
            shape.text_frame.text
            for shape in slide.shapes
            if shape.has_text_frame and shape.text_frame.text.strip()
        ]
        if texts:
            parts.append(f"[Slide {i}]\n" + "\n".join(texts))
    return "\n\n".join(parts)


_XLSX_MAX_ROWS_PER_SHEET = 2000


def _parse_xlsx(data: bytes) -> str:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    parts: list[str] = []
    for ws in wb.worksheets:
        lines: list[str] = []
        for row in ws.iter_rows(max_row=_XLSX_MAX_ROWS_PER_SHEET, values_only=True):
            cells = ["" if c is None else str(c) for c in row]
            if any(c.strip() for c in cells):
                lines.append(" | ".join(cells))
        if lines:
            parts.append(f"[Sheet: {ws.title}]\n" + "\n".join(lines))
    wb.close()
    return "\n\n".join(parts)


def _parse_csv(data: bytes) -> str:
    text = _decode(data)
    lines = text.splitlines()
    delim = "\t" if lines and "\t" in lines[0] else ","
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    return "\n".join(" | ".join(row) for row in reader if any(c.strip() for c in row))


def _parse_json(data: bytes) -> str:
    parsed = json.loads(_decode(data))
    return json.dumps(parsed, indent=2, ensure_ascii=False)


def _parse_yaml(data: bytes) -> str:
    # YAML is already human-readable text — validate it parses, store as-is.
    import yaml

    text = _decode(data)
    yaml.safe_load(text)
    return text


_PARSERS = {
    ".txt": _parse_text,
    ".md": _parse_text,
    ".markdown": _parse_text,
    ".pdf": _parse_pdf,
    ".docx": _parse_docx,
    ".html": _parse_html,
    ".htm": _parse_html,
    ".pptx": _parse_pptx,
    ".xlsx": _parse_xlsx,
    ".csv": _parse_csv,
    ".tsv": _parse_csv,
    ".json": _parse_json,
    ".yaml": _parse_yaml,
    ".yml": _parse_yaml,
}

SUPPORTED_TEXT_EXTENSIONS = frozenset(_PARSERS)


def parse_document(filename: str, ext: str, data: bytes) -> str:
    """Extract text from an uploaded document. Raises DocumentParseError."""
    parser = _PARSERS.get(ext)
    if parser is None:
        raise DocumentParseError(f"Unsupported file type: {ext}")
    try:
        text = parser(data)
    except DocumentParseError:
        raise
    except Exception as e:
        raise DocumentParseError(f"Could not read {ext.lstrip('.').upper()} file '{filename}': {e}") from e
    if not text.strip():
        raise DocumentParseError(
            f"No text could be extracted from '{filename}'. "
            "If this is a scanned/image PDF, upload page images instead (vision extraction)."
        )
    return text
