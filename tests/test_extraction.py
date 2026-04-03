"""
tests/test_extraction.py - Tests for text extraction utilities.
"""
import io
import sys
from pathlib import Path
import tempfile
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from extract_text import _extract_md, _extract_html, _extract_pdf, _ocr_pages
from utils import mask_sensitive, file_size_mb, compute_report_id, ensure_dir, JSONLWriter


def _make_text_pdf(tmp_path: Path, text: str = "Hello pentest world") -> Path:
    """Create a minimal PDF with an embedded text layer using PyMuPDF."""
    import fitz
    pdf_path = tmp_path / "sample.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 100), text)
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def _make_blank_pdf(tmp_path: Path) -> Path:
    """Create a PDF with no embedded text (simulates a scanned page)."""
    import fitz
    pdf_path = tmp_path / "blank.pdf"
    doc = fitz.open()
    doc.new_page()  # blank — no text inserted
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


class TestExtractMd:
    def test_reads_markdown(self, tmp_path):
        md_file = tmp_path / "test.md"
        md_file.write_text("# Hello\nThis is a test.", encoding="utf-8")
        result = _extract_md(md_file)
        assert "Hello" in result
        assert "This is a test." in result

    def test_empty_file(self, tmp_path):
        md_file = tmp_path / "empty.md"
        md_file.write_text("", encoding="utf-8")
        assert _extract_md(md_file) == ""


class TestExtractHtml:
    def test_strips_tags(self, tmp_path):
        html_file = tmp_path / "test.html"
        html_file.write_text(
            "<html><body><h1>Title</h1><p>Content here</p></body></html>",
            encoding="utf-8",
        )
        result = _extract_html(html_file)
        assert "Title" in result
        assert "Content here" in result
        assert "<h1>" not in result

    def test_removes_script_style(self, tmp_path):
        html_file = tmp_path / "test.html"
        html_file.write_text(
            "<html><head><script>alert('xss')</script></head>"
            "<body><p>Real content</p></body></html>",
            encoding="utf-8",
        )
        result = _extract_html(html_file)
        assert "Real content" in result
        assert "alert" not in result


class TestMaskSensitive:
    def test_masks_ip(self):
        text = "Server at 192.168.1.100 responded."
        assert "[IP_REDACTED]" in mask_sensitive(text)
        assert "192.168.1.100" not in mask_sensitive(text)

    def test_masks_email(self):
        text = "Contact admin@example.com for details."
        assert "[EMAIL_REDACTED]" in mask_sensitive(text)
        assert "admin@example.com" not in mask_sensitive(text)

    def test_masks_password(self):
        text = "password: supersecret123"
        result = mask_sensitive(text)
        assert "[REDACTED]" in result
        assert "supersecret123" not in result

    def test_no_false_positives(self):
        text = "No sensitive data here."
        assert mask_sensitive(text) == text


class TestFileHelpers:
    def test_file_size_mb(self, tmp_path):
        f = tmp_path / "sample.txt"
        f.write_bytes(b"x" * 1024 * 1024)  # exactly 1 MB
        assert abs(file_size_mb(f) - 1.0) < 0.01

    def test_compute_report_id_stable(self, tmp_path):
        f = tmp_path / "report.txt"
        f.write_text("content")
        id1 = compute_report_id(f)
        id2 = compute_report_id(f)
        assert id1 == id2
        assert len(id1) == 16

    def test_ensure_dir(self, tmp_path):
        new_dir = tmp_path / "a" / "b" / "c"
        result = ensure_dir(new_dir)
        assert result.is_dir()


class TestExtractPdf:
    def test_extracts_text_from_text_pdf(self, tmp_path):
        pdf_path = _make_text_pdf(tmp_path, "SQL injection vulnerability found")
        result = _extract_pdf(pdf_path)
        assert "SQL" in result or len(result.strip()) > 0  # text layer present

    def test_blank_pdf_attempts_ocr(self, tmp_path):
        """For a blank PDF, _extract_pdf should call _ocr_pages."""
        pdf_path = _make_blank_pdf(tmp_path)
        with patch("extract_text._ocr_pages", return_value=[""]) as mock_ocr:
            _extract_pdf(pdf_path)
            mock_ocr.assert_called_once()

    def test_text_pdf_does_not_trigger_ocr(self, tmp_path):
        """A PDF with a text layer must NOT call _ocr_pages."""
        pdf_path = _make_text_pdf(tmp_path, "This is a real text layer")
        with patch("extract_text._ocr_pages") as mock_ocr:
            _extract_pdf(pdf_path)
            mock_ocr.assert_not_called()

    def test_skip_ocr_flag_honored(self, tmp_path):
        """When skip_ocr=True, _ocr_pages must NOT be called regardless of page content."""
        pdf_path = _make_blank_pdf(tmp_path)
        with patch("extract_text._ocr_pages") as mock_ocr:
            result = _extract_pdf(pdf_path, skip_ocr=True)
            mock_ocr.assert_not_called()
            assert result.strip() == ""


class TestOcrPagesFallback:
    def test_graceful_fallback_when_pytesseract_missing(self, tmp_path):
        """_ocr_pages should return pages unchanged if pytesseract is not installed."""
        import fitz
        pdf_path = _make_blank_pdf(tmp_path)
        doc = fitz.open(str(pdf_path))
        pages = [""]
        indices = [0]

        with patch.dict("sys.modules", {"pytesseract": None}):
            result = _ocr_pages(doc, pages, indices)
        doc.close()
        # Should return original pages list unchanged (graceful degradation)
        assert result == pages


class TestMinWordsHeuristic:
    def test_process_report_skips_short_text(self, tmp_path):
        """process_report should return [] when extracted text is below MIN_WORDS."""
        sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
        from process_reports import process_report
        from config import get_config

        pdf_path = _make_text_pdf(tmp_path, "Only five words here")
        cfg = get_config(["--max_reports", "1"])
        cfg.max_file_size_mb = 100.0

        # Patch extract_text to return a very short string (< 20 words)
        with patch("process_reports.extract_text", return_value="Too short text"):
            result = process_report(pdf_path, tmp_path, cfg)
        assert result == [], "Expected empty list when extracted text is below MIN_WORDS"

    def test_process_report_accepts_sufficient_text(self, tmp_path):
        """process_report should not skip reports with >= MIN_WORDS words."""
        sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
        from process_reports import process_report
        from config import get_config

        pdf_path = _make_text_pdf(tmp_path)
        cfg = get_config(["--max_reports", "1"])
        cfg.max_file_size_mb = 100.0

        long_text = " ".join(["This is a valid pentest finding with enough words"] * 5)
        with patch("process_reports.extract_text", return_value=long_text):
            # May return [] if segmentation finds nothing, but should not be
            # skipped by the word-count guard
            with patch("process_reports.logger") as mock_log:
                process_report(pdf_path, tmp_path, cfg)
                # Ensure the 'too short' warning was NOT logged
                logged_msgs = [
                    str(c) for c in mock_log.warning.call_args_list
                ]
                assert not any("too short" in m for m in logged_msgs)


class TestJSONLWriter:
    def test_writes_records_to_file(self, tmp_path):
        out = tmp_path / "out.jsonl"
        records = [{"a": 1}, {"b": 2}, {"c": 3}]
        with JSONLWriter(out) as writer:
            for rec in records:
                writer.write(rec)

        lines = out.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 3
        assert {"a": 1} == __import__("json").loads(lines[0])

    def test_appends_on_successive_opens(self, tmp_path):
        out = tmp_path / "out.jsonl"
        with JSONLWriter(out) as writer:
            writer.write({"x": 1})
        with JSONLWriter(out) as writer:
            writer.write({"x": 2})

        lines = out.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2

    def test_truncates_in_write_mode(self, tmp_path):
        out = tmp_path / "out.jsonl"
        with JSONLWriter(out) as writer:
            writer.write({"x": 1})
            writer.write({"x": 2})
        with JSONLWriter(out, mode="w") as writer:
            writer.write({"x": 3})

        lines = out.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1

    def test_raises_when_not_entered(self, tmp_path):
        out = tmp_path / "out.jsonl"
        writer = JSONLWriter(out)
        with pytest.raises(RuntimeError):
            writer.write({"x": 1})

    def test_unicode_preserved(self, tmp_path):
        out = tmp_path / "out.jsonl"
        with JSONLWriter(out) as writer:
            writer.write({"msg": "héllo wörld"})

        import json
        line = out.read_text(encoding="utf-8").strip()
        assert json.loads(line)["msg"] == "héllo wörld"

