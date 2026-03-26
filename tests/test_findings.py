"""
tests/test_findings.py - Tests for finding splitting and heuristics.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from split_findings import split_findings, _build_finding
from heuristics import classify_finding


class TestSplitFindings:
    def test_empty_text_returns_empty_list(self):
        assert split_findings("") == []

    def test_single_finding_no_header(self):
        text = "There is a SQL injection vulnerability in the login form."
        result = split_findings(text)
        assert len(result) == 1
        assert result[0]["title"] == "Finding"

    def test_multiple_findings_with_headers(self):
        text = (
            "Finding 1: SQL Injection\n"
            "The login form is vulnerable to SQL injection.\n"
            "\n"
            "Finding 2: XSS\n"
            "Reflected XSS found on the search endpoint.\n"
        )
        result = split_findings(text)
        assert len(result) >= 1
        titles = [r["title"] for r in result]
        assert any("SQL Injection" in t for t in titles)

    def test_severity_header(self):
        text = (
            "High: Remote Code Execution\n"
            "An attacker can execute arbitrary code via the upload endpoint.\n"
        )
        result = split_findings(text)
        assert len(result) >= 1

    def test_build_finding_has_required_keys(self):
        result = _build_finding("Test Title", "Some body text")
        for key in ("title", "description", "technical_details", "recommendation"):
            assert key in result

    def test_recommendation_extracted(self):
        body = (
            "The application is vulnerable.\n"
            "Recommendation: Use parameterized queries to prevent injection.\n"
        )
        result = _build_finding("SQL Injection", body)
        assert result["recommendation"] is not None
        assert "parameterized" in result["recommendation"]


class TestHeuristics:
    def test_sql_injection_classification(self):
        result = classify_finding("SQL injection found in login form")
        assert result["vuln_type"] == "SQLi"
        assert result["cwe"] == "CWE-89"
        assert result["owasp"] == "A03:2021"

    def test_xss_classification(self):
        result = classify_finding("Reflected XSS on search page")
        assert result["vuln_type"] == "XSS"

    def test_rce_classification(self):
        result = classify_finding("Remote code execution via file upload")
        assert result["vuln_type"] == "RCE"

    def test_idor_classification(self):
        result = classify_finding("Insecure direct object reference allows access")
        assert result["vuln_type"] == "IDOR"

    def test_severity_extraction(self):
        result = classify_finding("High severity: SQL injection found")
        assert result["severity"] == "high"

    def test_cvss_extraction(self):
        result = classify_finding("CVSS score: 9.8 - Critical SQL injection")
        assert result["cvss_score"] == "9.8"

    def test_unknown_vuln_returns_none(self):
        result = classify_finding("The application uses an old version of jQuery")
        assert result["vuln_type"] is None

    def test_informational_normalised(self):
        result = classify_finding("Informational: Missing security headers")
        assert result["severity"] == "info"
