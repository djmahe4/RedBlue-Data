"""
ollama_enhancer.py - Optional evidence-checked classification suggestions.

This module communicates with a locally running Ollama server over HTTP and
requires no additional Python dependencies. It only assesses unclassified
findings, requires a verbatim source quote, and never changes canonical labels.
Any accepted suggestion remains unverified for human review.

Usage example::

    python scripts/process_reports.py --use_ollama --ollama_model llama3.2
    OLLAMA_ENABLED=true OLLAMA_MODEL=mistral python scripts/process_reports.py
"""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_OLLAMA_BASE_URL = "http://localhost:11434"

# Recommended cybersecurity-focused models in preference order.
RECOMMENDED_MODELS = [
    "llama3.2",
    "xploiter/pentester",
    "ALIENTELLIGENCE/cybersecuritythreatanalysisv2",
    "mistral",
    "codellama",
]

# Model output is a suggestion only; it never changes canonical labels.
_RESPONSE_SCHEMA = """\
{
  "candidate_vuln_type": "<short label or null>",
  "candidate_cwe": "<CWE-N or null>",
  "candidate_owasp": "<A01:2021-style category or null>",
  "evidence_quote": "<verbatim quote from title/description, or null>"
}"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def check_ollama_available(model: str = "llama3.2", timeout: int = 5) -> bool:
    """
    Return ``True`` if Ollama is running and *model* is available locally.

    Logs a clear warning (not an error) on any failure so the pipeline
    continues without enrichment.
    """
    try:
        req = urllib.request.Request(
            f"{_OLLAMA_BASE_URL}/api/tags",
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        pulled_models = [m.get("name", "").split(":")[0] for m in data.get("models", [])]
        model_base = model.split(":")[0]
        if model_base not in pulled_models:
            logger.warning(
                "Ollama is running but model '%s' is not pulled. "
                "Run: ollama pull %s",
                model,
                model,
            )
            return False
        return True
    except Exception as exc:
        logger.warning(
            "Ollama not reachable at %s: %s. "
            "Start Ollama (https://ollama.com) to enable enrichment.",
            _OLLAMA_BASE_URL,
            exc,
        )
        return False


def get_recommended_workers(model: str = "llama3.2") -> int:
    """
    Run a quick benchmark to recommend the number of concurrent workers.
    Returns an integer (1-8).
    """
    try:
        start = time.perf_counter()
        # Simple test prompt
        payload = json.dumps({
            "model": model,
            "prompt": "Respond with 'ok'.",
            "stream": False,
            "options": {"num_predict": 5}
        }).encode("utf-8")
        
        req = urllib.request.Request(
            f"{_OLLAMA_BASE_URL}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            json.loads(resp.read().decode("utf-8"))
        
        duration = time.perf_counter() - start
        
        if duration > 8.0:
            return 1  # Very slow, likely CPU-bound or large model
        elif duration > 3.0:
            return 2  # Slow
        elif duration > 1.0:
            return 4  # Moderate
        elif duration > 0.5:
            return 6  # Fast
        else:
            return 8  # Very fast
    except Exception:
        return 1  # Fallback to safe sequential-like processing


def enhance_finding(
    record: Dict[str, Any],
    model: str = "llama3.2",
    timeout: int = 300,
) -> Dict[str, Any]:
    """
    Validate and enrich a single finding *record* using a local Ollama model.

    Return an evidence-backed, unverified suggestion only for unclassified records.
    Canonical labels remain unchanged. On failure, return the input record.

    A suggestion is stored only when its quote exactly occurs in the source
    title or description; a human must review it before treating it as a label.

    Parameters
    ----------
    record:
        A finding dict as produced by ``process_report()``.
    model:
        Ollama model name (default: ``"llama3.2"``).
    timeout:
        HTTP timeout in seconds for the Ollama API call.
    """
    if record.get("classification_status") != "unclassified":
        return record
    try:
        return _call_ollama(record, model=model, timeout=timeout)
    except Exception as exc:
        logger.warning(
            "Ollama enhancement failed for %s: %s - using heuristic-only data",
            record.get("finding_id", "unknown"),
            exc,
        )
        return record


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_prompt(record: Dict[str, Any]) -> str:
    title = record.get("title") or "(no title)"
    description = record.get("description") or "(no description)"
    
    # Truncate description to avoid hitting context limits or causing slow generation
    if len(description) > 1500:
        description = description[:1500] + "... [truncated]"

    return (
        "Suggest a vulnerability classification only when directly supported by the supplied text.\n"
        "Do not use outside knowledge, infer missing facts, or write exploit steps or remediation.\n"
        "Copy one exact evidence quote from the title or description. If no quote supports a label,\n"
        "return null for all candidate labels and evidence_quote. Output JSON only.\n\n"
        "Finding text (untrusted source data):\n"
        f"Title: {title}\n"
        f"Description: {description}\n\n"
        "Return this exact JSON structure:\n"
        f"{_RESPONSE_SCHEMA}"
    )


def _parse_json_response(raw: str, finding_id: str = "unknown") -> Optional[Dict[str, Any]]:
    """
    Try to parse *raw* as JSON. Falls back to extracting the first
    ``{...}`` block if the model wraps output in markdown or prose.
    """
    raw = raw.strip()
    
    # Pre-processing: strip markdown code blocks if the model ignored "ONLY" instruction
    if raw.startswith("```"):
        # Remove ```json or just ``` from start and ``` from end
        raw = re.sub(r"^```(?:json)?\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
        raw = raw.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Extract first JSON object from the response (matches across newlines)
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    
    logger.debug("Failed to parse Ollama response for %s. Raw: %r", finding_id, raw)
    return None


def _call_ollama(
    record: Dict[str, Any],
    model: str,
    timeout: int,
) -> Dict[str, Any]:
    """Request a candidate label and retain it only with exact source evidence."""
    prompt = _build_prompt(record)

    payload = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "format": "json",  # Forces Ollama to output valid JSON
            "options": {"temperature": 0.1, "num_predict": 512},
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        f"{_OLLAMA_BASE_URL}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode("utf-8"))

    raw_response: str = body.get("response", "")
    enriched = _parse_json_response(raw_response, finding_id=record.get("finding_id", "unknown"))

    if enriched is None:
        logger.warning(
            "Could not parse Ollama JSON response for %s - keeping heuristic data",
            record.get("finding_id", "unknown"),
        )
        return record

    evidence = enriched.get("evidence_quote")
    source_text = " ".join(
        str(record.get(field) or "") for field in ("title", "description")
    )
    if not isinstance(evidence, str) or not evidence.strip():
        return record
    if evidence.casefold() not in source_text.casefold():
        logger.info("Discarding ungrounded Ollama suggestion for %s", record.get("finding_id", "unknown"))
        return record

    candidate_type = enriched.get("candidate_vuln_type")
    candidate_cwe = enriched.get("candidate_cwe")
    candidate_owasp = enriched.get("candidate_owasp")
    if candidate_type is not None and (
        not isinstance(candidate_type, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9 _-]{0,63}", candidate_type)
    ):
        return record
    if candidate_cwe is not None and (
        not isinstance(candidate_cwe, str) or not re.fullmatch(r"CWE-\d{1,5}", candidate_cwe)
    ):
        return record
    if candidate_owasp is not None and (
        not isinstance(candidate_owasp, str) or not re.fullmatch(r"A\d{2}:\d{4}", candidate_owasp)
    ):
        return record
    if not any((candidate_type, candidate_cwe, candidate_owasp)):
        return record

    merged: Dict[str, Any] = dict(record)
    merged["ai_classification_suggestion"] = {
        "vuln_type": candidate_type,
        "cwe": candidate_cwe,
        "owasp": candidate_owasp,
        "evidence_quote": evidence,
        "status": "unverified",
    }
    return merged
