"""
tests/test_ollama_enhancer.py - Tests for the optional Ollama enrichment module.

All tests mock network calls so they run without a live Ollama instance.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from ollama_enhancer import (
    _build_prompt,
    _call_ollama,
    _parse_json_response,
    check_ollama_available,
    enhance_finding,
)

# ---------------------------------------------------------------------------
# Sample fixtures
# ---------------------------------------------------------------------------

_SAMPLE_RECORD = {
    "report_id": "abc123",
    "finding_id": "abc123_0001",
    "vendor": "test_vendor",
    "title": "SQL Injection in Login Form",
    "description": "The login form passes unsanitised input directly to the database.",
    "technical_details": None,
    "recommendation": None,
    "vuln_type": "SQLi",
    "cwe": "CWE-89",
    "owasp": "A03:2021",
    "severity": "high",
    "cvss_score": None,
}

_GOOD_OLLAMA_RESPONSE = json.dumps({
    "cwe": "CWE-89",
    "owasp": "A03:2021",
    "severity": "critical",
    "vuln_type": "SQLi",
    "enhanced_description": "Classic SQL injection allows full DB dump.",
    "attack_vector": "Craft a payload: ' OR 1=1--",
    "remediation": "Use parameterised queries and an ORM.",
    "quality_score": 8,
})


# ---------------------------------------------------------------------------
# _build_prompt
# ---------------------------------------------------------------------------

class TestBuildPrompt:
    def test_contains_title(self):
        prompt = _build_prompt(_SAMPLE_RECORD)
        assert "SQL Injection in Login Form" in prompt

    def test_contains_cwe(self):
        prompt = _build_prompt(_SAMPLE_RECORD)
        assert "CWE-89" in prompt

    def test_handles_missing_fields(self):
        prompt = _build_prompt({"finding_id": "x"})
        assert "(no title)" in prompt
        assert "(no description)" in prompt


# ---------------------------------------------------------------------------
# _parse_json_response
# ---------------------------------------------------------------------------

class TestParseJsonResponse:
    def test_clean_json(self):
        result = _parse_json_response('{"a": 1}')
        assert result == {"a": 1}

    def test_json_wrapped_in_markdown(self):
        raw = "Here is the result:\n```json\n{\"a\": 1}\n```\n"
        result = _parse_json_response(raw)
        assert result is not None
        assert result["a"] == 1

    def test_returns_none_on_garbage(self):
        assert _parse_json_response("not json at all") is None

    def test_extracts_first_json_object_from_prose(self):
        raw = 'Some prose first. {"key": "value"} more prose.'
        result = _parse_json_response(raw)
        assert result is not None
        assert result["key"] == "value"


# ---------------------------------------------------------------------------
# check_ollama_available
# ---------------------------------------------------------------------------

class TestCheckOllamaAvailable:
    def _tags_response(self, model_name: str) -> bytes:
        return json.dumps({"models": [{"name": model_name}]}).encode()

    def test_returns_true_when_model_present(self):
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = self._tags_response("llama3.2")

        with patch("urllib.request.urlopen", return_value=mock_resp):
            assert check_ollama_available("llama3.2") is True

    def test_returns_false_when_model_absent(self):
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = self._tags_response("other_model")

        with patch("urllib.request.urlopen", return_value=mock_resp):
            assert check_ollama_available("llama3.2") is False

    def test_returns_false_on_connection_error(self):
        import urllib.error
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
            assert check_ollama_available("llama3.2") is False

    def test_logs_warning_on_failure(self, caplog):
        import urllib.error
        import logging
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
            with caplog.at_level(logging.WARNING, logger="ollama_enhancer"):
                check_ollama_available("llama3.2")
        assert any("not reachable" in r.message.lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# enhance_finding
# ---------------------------------------------------------------------------

class TestEnhanceFinding:
    def _mock_urlopen(self, response_text: str):
        """Return a context-manager mock that yields *response_text* from .read()."""
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = json.dumps({"response": response_text}).encode()
        return mock_resp

    def test_merges_enrichments_into_record(self):
        with patch("urllib.request.urlopen", return_value=self._mock_urlopen(_GOOD_OLLAMA_RESPONSE)):
            result = enhance_finding(dict(_SAMPLE_RECORD), model="llama3.2")

        assert result["severity"] == "critical"
        assert result["enhanced_description"] == "Classic SQL injection allows full DB dump."
        assert result["attack_vector"] == "Craft a payload: ' OR 1=1--"
        assert result["recommendation"] == "Use parameterised queries and an ORM."
        assert result["quality_score"] == 8

    def test_does_not_overwrite_existing_recommendation(self):
        record = dict(_SAMPLE_RECORD)
        record["recommendation"] = "Existing recommendation."
        with patch("urllib.request.urlopen", return_value=self._mock_urlopen(_GOOD_OLLAMA_RESPONSE)):
            result = enhance_finding(record, model="llama3.2")
        assert result["recommendation"] == "Existing recommendation."

    def test_returns_original_on_network_error(self):
        import urllib.error
        original = dict(_SAMPLE_RECORD)
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
            result = enhance_finding(original, model="llama3.2")
        assert result == original

    def test_returns_original_on_unparseable_response(self):
        original = dict(_SAMPLE_RECORD)
        with patch("urllib.request.urlopen", return_value=self._mock_urlopen("not valid json")):
            result = enhance_finding(original, model="llama3.2")
        assert result == original

    def test_logs_warning_on_failure(self, caplog):
        import urllib.error
        import logging
        original = dict(_SAMPLE_RECORD)
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
            with caplog.at_level(logging.WARNING, logger="ollama_enhancer"):
                enhance_finding(original, model="llama3.2")
        assert any("failed" in r.message.lower() for r in caplog.records)

    def test_skips_placeholder_values(self):
        """Fields returned as 'unknown' by the model must not overwrite good data."""
        response = json.dumps({
            "cwe": "unknown",
            "owasp": "",
            "severity": "high",
            "vuln_type": "SQLi",
            "enhanced_description": "Better desc.",
            "attack_vector": "",
            "remediation": "",
            "quality_score": 5,
        })
        record = dict(_SAMPLE_RECORD)
        with patch("urllib.request.urlopen", return_value=self._mock_urlopen(response)):
            result = enhance_finding(record, model="llama3.2")
        # CWE-89 should be preserved (not overwritten with 'unknown')
        assert result["cwe"] == "CWE-89"
        # OWASP should be preserved (not overwritten with '')
        assert result["owasp"] == "A03:2021"
