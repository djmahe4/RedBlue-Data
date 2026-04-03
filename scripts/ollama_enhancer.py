"""
ollama_enhancer.py - Optional Ollama integration for dataset validation and enrichment.

This module is imported ONLY when ``use_ollama_validation=True`` in Config.
It communicates with a locally running Ollama server over HTTP and requires
no additional Python dependencies beyond the standard library.

Graceful fallback: every public function logs a warning and returns the
original data unchanged when Ollama is unavailable or returns an error.
No CI/CD dependencies are introduced; this is a developer-only feature.

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
from typing import Any, Callable, Dict, Optional

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

# JSON schema that the model is asked to fill in.
_RESPONSE_SCHEMA = """\
{
  "cwe": "<corrected CWE ID e.g. CWE-89, or keep original>",
  "owasp": "<corrected OWASP category e.g. A03:2021, or keep original>",
  "severity": "<one of: critical|high|medium|low|info>",
  "vuln_type": "<concise vulnerability type label>",
  "enhanced_description": "<richer technical description in 2-3 sentences>",
  "attack_vector": "<how an attacker would exploit this in 1-2 sentences>",
  "remediation": "<specific remediation steps in 2-3 sentences>",
  "quality_score": <integer 1-10 reflecting finding richness>
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


def enhance_finding(
    record: Dict[str, Any],
    model: str = "llama3.2",
    timeout: int = 30,
) -> Dict[str, Any]:
    """
    Validate and enrich a single finding *record* using a local Ollama model.

    Returns the (possibly enriched) record.  On **any** failure the original
    record is returned unchanged (graceful fallback - no pipeline breakage).

    Fields that may be added or updated:
    - ``cwe``, ``owasp``, ``severity``, ``vuln_type`` - corrected by the LLM
    - ``enhanced_description`` - richer technical description
    - ``attack_vector`` - how an attacker would exploit the finding
    - ``recommendation`` - enriched remediation (only if currently empty)
    - ``quality_score`` - integer 1-10 from the LLM

    Parameters
    ----------
    record:
        A finding dict as produced by ``process_report()``.
    model:
        Ollama model name (default: ``"llama3.2"``).
    timeout:
        HTTP timeout in seconds for the Ollama API call.
    """
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
    current_cwe = record.get("cwe") or "Unknown"
    current_owasp = record.get("owasp") or "Unknown"
    current_severity = record.get("severity") or "Unknown"
    current_vuln_type = record.get("vuln_type") or "Unknown"

    return (
        "You are a senior penetration-testing expert reviewing a security finding.\n"
        "Respond ONLY with a valid JSON object - no markdown fences, no explanation.\n\n"
        "Finding:\n"
        f"  Title       : {title}\n"
        f"  Description : {description}\n"
        f"  CWE         : {current_cwe}\n"
        f"  OWASP       : {current_owasp}\n"
        f"  Severity    : {current_severity}\n"
        f"  Vuln type   : {current_vuln_type}\n\n"
        "Fill in this exact JSON structure:\n"
        f"{_RESPONSE_SCHEMA}"
    )


def _parse_json_response(raw: str) -> Optional[Dict[str, Any]]:
    """
    Try to parse *raw* as JSON.  Falls back to extracting the first
    ``{...}`` block if the model wraps output in markdown or prose.
    """
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Extract first JSON object from the response
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None


def _call_ollama(
    record: Dict[str, Any],
    model: str,
    timeout: int,
) -> Dict[str, Any]:
    """Make the Ollama API call and merge enrichments back into *record*."""
    prompt = _build_prompt(record)

    payload = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
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
    enriched = _parse_json_response(raw_response)

    if enriched is None:
        logger.warning(
            "Could not parse Ollama JSON response for %s - keeping heuristic data",
            record.get("finding_id", "unknown"),
        )
        return record

    # Merge enrichments back: only override existing fields when the LLM
    # returns a non-empty, non-placeholder value.
    merged: Dict[str, Any] = dict(record)

    _PLACEHOLDER = {"unknown", ""}
    for field in ("cwe", "owasp", "severity", "vuln_type"):
        new_val = enriched.get(field)
        if new_val and str(new_val).lower() not in _PLACEHOLDER:
            merged[field] = new_val

    if enriched.get("enhanced_description"):
        merged["enhanced_description"] = enriched["enhanced_description"]

    if enriched.get("attack_vector"):
        merged["attack_vector"] = enriched["attack_vector"]

    # Only fill recommendation if the heuristic pipeline left it empty.
    if enriched.get("remediation") and not merged.get("recommendation"):
        merged["recommendation"] = enriched["remediation"]

    quality = enriched.get("quality_score")
    if quality is not None:
        try:
            merged["quality_score"] = int(quality)
        except (TypeError, ValueError):
            pass

    return merged
