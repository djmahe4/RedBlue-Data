"""
extract_text.py - Text extraction from PDF, HTML, Markdown and DOCX files.

For image-only (scanned) PDFs, falls back to Tesseract OCR via pytesseract.
Requires: tesseract-ocr system package + pytesseract Python package.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# DPI used when rendering PDF pages for OCR.  Higher = better accuracy but
# slower.  Override via OCR_DPI env var.
_OCR_DPI = int(os.environ.get("OCR_DPI", "300"))


def extract_text(path: Path, skip_ocr: bool = False) -> str:
    """
    Extract plain text from a file.

    Supported formats: pdf, html, md, docx.
    Returns an empty string on any error.
    """
    ext = path.suffix.lower().lstrip(".")
    try:
        if ext == "pdf":
            return _extract_pdf(path, skip_ocr=skip_ocr)
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


def _extract_pdf(path: Path, skip_ocr: bool = False) -> str:
    import fitz  # type: ignore[import]  # pymupdf

    doc = fitz.open(str(path))
    pages: list[str] = []
    ocr_needed: list[int] = []  # page indices that yielded no text

    for i in range(len(doc)):
        page = doc[i]
        text = page.get_text().strip()
        if text:
            pages.append(text)
        else:
            pages.append("")  # placeholder; may be replaced by OCR
            ocr_needed.append(i)

    if ocr_needed:
        if skip_ocr:
            logger.info("%s: %d page(s) have no embedded text – skipping OCR pass per config", path.name, len(ocr_needed))
        else:
            logger.debug(
                "%s: %d/%d pages have no embedded text – attempting OCR",
                path.name,
                len(ocr_needed),
                len(pages),
            )
            pages = _ocr_pages(doc, pages, ocr_needed, path)

    doc.close()
    return "\n".join(pages)


def _ocr_pages(
    doc,
    pages: list[str],
    indices: list[int],
    pdf_path: Path | None = None,
) -> list[str]:
    """OCR blank PDF pages with configured models, then fall back to Tesseract."""
    provider = os.environ.get("OCR_PROVIDER", "auto").lower()
    model_ocr_configured = provider in {"api", "ollama", "nemotron"} or (
        provider == "auto"
        and (
            os.environ.get("OCR_API_URL")
            or os.environ.get("NEMOTRON_OCR_URL")
            or os.environ.get("OLLAMA_OCR_MODEL")
            or (os.environ.get("OCR_MODEL") and os.environ.get("OLLAMA_BASE_URL"))
        )
    )
    if pdf_path is not None and model_ocr_configured:
        from tools.pdf_ocr import ocr_pdf_page

        fallback_indices = []
        for index in indices:
            try:
                result = ocr_pdf_page(pdf_path, index + 1)
                pages[index] = str(result.get("markdown") or "").strip()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Model OCR failed on page %d of %s: %s", index + 1, pdf_path, exc)
                fallback_indices.append(index)
        indices = fallback_indices
        if not indices:
            return pages
    try:
        import pytesseract  # type: ignore[import]
        from PIL import Image  # type: ignore[import]
        import io
    except ImportError:
        logger.warning(
            "pytesseract / Pillow not installed – skipping OCR for %d page(s). "
            "Run: pip install pytesseract pillow",
            len(indices),
        )
        return pages

    import fitz  # type: ignore[import]  # already imported but needed locally

    zoom = _OCR_DPI / 72  # fitz default is 72 dpi
    mat = fitz.Matrix(zoom, zoom)

    for i in indices:
        page = doc[i]
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        try:
            text = pytesseract.image_to_string(img, lang="eng")
            pages[i] = text.strip()
        except Exception as exc:  # noqa: BLE001
            logger.warning("OCR failed on page %d: %s", i, exc)

    return pages


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
