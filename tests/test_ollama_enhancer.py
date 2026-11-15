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
    get_recommended_workers,
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
    "vuln_type": None,
    "cwe": None,
    "owasp": None,
    "severity": None,
    "cvss_score": None,
    "classification_status": "unclassified",
}

_GOOD_OLLAMA_RESPONSE = json.dumps({
    "candidate_cwe": "CWE-89",
    "candidate_owasp": "A03:2021",
    "candidate_vuln_type": "SQLi",
    "evidence_quote": "The login form passes unsanitised input directly to the database.",
})


# ---------------------------------------------------------------------------
# _build_prompt
# ---------------------------------------------------------------------------

class TestBuildPrompt:
    def test_contains_title(self):
        prompt = _build_prompt(_SAMPLE_RECORD)
        assert "SQL Injection in Login Form" in prompt

    def test_requires_verbatim_source_evidence(self):
        prompt = _build_prompt(_SAMPLE_RECORD)
        assert "exact evidence quote" in prompt
        assert "outside knowledge" in prompt

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

    def test_json_wrapped_in_bare_markdown(self):
        raw = "```\n{\"b\": 2}\n```"
        result = _parse_json_response(raw)
        assert result is not None
        assert result["b"] == 2

    def test_returns_none_on_garbage(self):
        assert _parse_json_response("not json at all") is None

    def test_extracts_first_json_object_from_prose(self):
        raw = 'Some prose first. {"key": "value"} more prose.'
        result = _parse_json_response(raw)
        assert result is not None
        assert result["key"] == "value"


# ---------------------------------------------------------------------------
# get_recommended_workers
# ---------------------------------------------------------------------------

class TestGetRecommendedWorkers:
    @patch("time.perf_counter")
    @patch("urllib.request.urlopen")
    def test_returns_low_workers_for_slow_server(self, mock_urlopen, mock_time):
        mock_time.side_effect = [0.0, 10.0]  # 10s duration
        mock_resp = MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.read.return_value = b'{"response": "ok"}'
        mock_urlopen.return_value = mock_resp

        assert get_recommended_workers() == 1

    @patch("time.perf_counter")
    @patch("urllib.request.urlopen")
    def test_returns_high_workers_for_fast_server(self, mock_urlopen, mock_time):
        mock_time.side_effect = [0.0, 0.1]  # 0.1s duration
        mock_resp = MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.read.return_value = b'{"response": "ok"}'
        mock_urlopen.return_value = mock_resp

        # Benchmark should return 8 for < 0.5s
        assert get_recommended_workers() == 8


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

    def test_adds_only_unverified_grounded_suggestion(self):
        with patch("urllib.request.urlopen", return_value=self._mock_urlopen(_GOOD_OLLAMA_RESPONSE)):
            result = enhance_finding(dict(_SAMPLE_RECORD), model="llama3.2")

        assert result["vuln_type"] is None
        assert result["cwe"] is None
        assert result["classification_status"] == "unclassified"
        assert result["ai_classification_suggestion"] == {
            "vuln_type": "SQLi",
            "cwe": "CWE-89",
            "owasp": "A03:2021",
            "evidence_quote": _SAMPLE_RECORD["description"],
            "status": "unverified",
        }

    def test_does_not_call_model_for_rule_matched_finding(self):
        record = dict(_SAMPLE_RECORD, classification_status="rule_matched", vuln_type="SQLi")
        with patch("urllib.request.urlopen") as urlopen:
            assert enhance_finding(record, model="llama3.2") == record
        urlopen.assert_not_called()

    def test_discards_suggestion_without_exact_source_quote(self):
        response = json.dumps({
            "candidate_cwe": "CWE-89",
            "candidate_owasp": "A03:2021",
            "candidate_vuln_type": "SQLi",
            "evidence_quote": "The database leaked all records.",
        })
        with patch("urllib.request.urlopen", return_value=self._mock_urlopen(response)):
            result = enhance_finding(dict(_SAMPLE_RECORD), model="llama3.2")
        assert "ai_classification_suggestion" not in result

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

    def test_rejects_invalid_candidate_identifiers(self):
        response = json.dumps({
            "candidate_cwe": "unknown",
            "candidate_owasp": "",
            "candidate_vuln_type": "SQLi",
            "evidence_quote": _SAMPLE_RECORD["description"],
        })
        with patch("urllib.request.urlopen", return_value=self._mock_urlopen(response)):
            result = enhance_finding(dict(_SAMPLE_RECORD), model="llama3.2")
        assert result["cwe"] is None
        assert result["owasp"] is None
        assert "ai_classification_suggestion" not in result
