"""
tests/test_segmentation.py - Tests for report segmentation.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from segment_report import segment_report


class TestSegmentReport:
    def test_returns_three_sections(self):
        result = segment_report("Some text here")
        assert set(result.keys()) == {"exec_summary", "findings_raw", "recommendations"}

    def test_executive_summary_detection(self):
        text = (
            "Executive Summary\n"
            "This engagement assessed the security posture.\n"
            "\n"
            "Findings\n"
            "Finding 1: SQL Injection\n"
        )
        result = segment_report(text)
        assert "security posture" in result["exec_summary"]

    def test_findings_detection(self):
        text = (
            "Findings\n"
            "SQL Injection was discovered on the login page.\n"
            "\n"
            "Recommendations\n"
            "Use parameterized queries.\n"
        )
        result = segment_report(text)
        assert "SQL Injection" in result["findings_raw"]
        assert "parameterized" in result["recommendations"]

    def test_empty_text_returns_empty_sections(self):
        result = segment_report("")
        assert result["exec_summary"] == ""
        assert result["findings_raw"] == ""
        assert result["recommendations"] == ""

    def test_no_headers_all_in_findings(self):
        text = "Line 1\nLine 2\nLine 3"
        result = segment_report(text)
        # Without any headers, all text should land in the default bucket
        assert "Line 1" in result["findings_raw"]
