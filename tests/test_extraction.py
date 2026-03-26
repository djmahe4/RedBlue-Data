"""
tests/test_extraction.py - Tests for text extraction utilities.
"""
import sys
from pathlib import Path
import tempfile

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from extract_text import _extract_md, _extract_html
from utils import mask_sensitive, file_size_mb, compute_report_id, ensure_dir


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
