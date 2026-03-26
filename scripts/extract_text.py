"""
extract_text.py - Text extraction from PDF, HTML, Markdown and DOCX files.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def extract_text(path: Path) -> str:
    """
    Extract plain text from a file.

    Supported formats: pdf, html, md, docx.
    Returns an empty string on any error.
    """
    ext = path.suffix.lower().lstrip(".")
    try:
        if ext == "pdf":
            return _extract_pdf(path)
        elif ext in ("html", "htm"):
            return _extract_html(path)
        elif ext == "md":
            return _extract_md(path)
        elif ext == "docx":
            return _extract_docx(path)
        else:
            logger.warning("Unsupported file type: %s", ext)
            return ""
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to extract text from %s: %s", path, exc)
        return ""


def _extract_pdf(path: Path) -> str:
    import fitz  # type: ignore[import]  # pymupdf

    doc = fitz.open(str(path))
    pages = []
    for page in doc:
        pages.append(page.get_text())
    doc.close()
    return "\n".join(pages)


def _extract_html(path: Path) -> str:
    from bs4 import BeautifulSoup  # type: ignore[import]

    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        soup = BeautifulSoup(fh.read(), "lxml")
    # Remove script / style noise
    for tag in soup(["script", "style"]):
        tag.decompose()
    return soup.get_text(separator="\n")


def _extract_md(path: Path) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _extract_docx(path: Path) -> str:
    from docx import Document  # type: ignore[import]

    doc = Document(str(path))
    return "\n".join(para.text for para in doc.paragraphs)
