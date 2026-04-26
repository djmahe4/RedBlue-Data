"""
ollama_enhancer.py - Optional Ollama integration for dataset validation and enrichment.

This module is imported ONLY when ``use_ollama_validation=True`` in Config.
It communicates with a locally running Ollama server over HTTP and requires
no additional Python dependencies beyond the standard library.

Graceful fallback: every public function logs a warning and returns the
original data unchanged when Ollama is unavailable or returns an error.
No CI/CD dependencies are introduced; this is a developer-only feature.

Modes
-----
1. **Validation/Correction mode** (``enhance_finding``):
   Validate existing heuristic labels, suggest enriched descriptions and fixes.
2. **Semantic mapping mode** (``map_external_record``):
   Convert an arbitrary external-dataset record to the unified RedBlue schema.

Caching
-------
LLM responses are cached on disk (JSON, keyed by SHA-256 of the prompt) to
avoid redundant API calls across runs.  Set ``cache_dir=None`` to disable.

Usage example::

    python scripts/process_reports.py --use_ollama --ollama_model llama3.2
    OLLAMA_ENABLED=true OLLAMA_MODEL=mistral python scripts/process_reports.py
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import urllib.error
import urllib.request
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

_OLLAMA_BASE_URL = "http://localhost:11434"

# Default on-disk cache directory. Set to None to disable caching (default).
# Pass an explicit Path to enable: enhance_finding(..., cache_dir=Path(".ollama_cache"))
_DEFAULT_CACHE_DIR: Optional[Path] = None

# Recommended cybersecurity-focused models in preference order.
RECOMMENDED_MODELS = [
    "llama3.2",
    "xploiter/pentester",
    "ALIENTELLIGENCE/cybersecuritythreatanalysisv2",
    "mistral",
    "codellama",
]

# JSON schema that the model is asked to fill in for validation/correction mode.
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

# JSON schema for semantic mapping (external records → unified schema).
_MAPPING_SCHEMA = """\
{
  "vuln_type": "<concise vulnerability type label or null>",
  "cwe": "<CWE ID e.g. CWE-89, or null>",
  "owasp": "<OWASP Top 10 category e.g. A03:2021, or null>",
  "severity": "<one of: critical|high|medium|low|info, or null>",
  "title": "<short vulnerability title or null>",
  "description": "<vulnerability description or null>",
  "recommendation": "<remediation guidance or null>",
  "red_suitable": <true if record is useful for offensive/red-team training>,
  "blue_suitable": <true if record is useful for defensive/blue-team training>,
  "confidence": <integer 1-10 reflecting mapping confidence>
}"""

# Few-shot examples for the mapping prompt.
_MAPPING_FEW_SHOT = """
Example 1:
External record: {"instruction": "Explain SQL injection", "response": "SQL injection allows ..."}
Output: {"vuln_type": "SQLi", "cwe": "CWE-89", "owasp": "A03:2021", "severity": "high",
         "title": "SQL Injection", "description": "SQL injection allows ...", "recommendation": null,
         "red_suitable": true, "blue_suitable": true, "confidence": 9}

Example 2:
External record: {"question": "What is XSS?", "answer": "Cross-site scripting is ..."}
Output: {"vuln_type": "XSS", "cwe": "CWE-79", "owasp": "A03:2021", "severity": "medium",
         "title": "Cross-Site Scripting", "description": "Cross-site scripting is ...", "recommendation": null,
         "red_suitable": true, "blue_suitable": true, "confidence": 8}
"""


# ---------------------------------------------------------------------------
# Response cache helpers
# ---------------------------------------------------------------------------

def _cache_key(prompt: str, model: str = "") -> str:
    return hashlib.sha256(f"{model}:{prompt}".encode("utf-8")).hexdigest()


def _load_cached(prompt: str, cache_dir: Optional[Path], model: str = "") -> Optional[Dict[str, Any]]:
    if cache_dir is None:
        return None
    key = _cache_key(prompt, model)
    cache_file = cache_dir / f"{key}.json"
    if cache_file.exists():
        try:
            with open(cache_file, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            pass
    return None


def _save_cached(prompt: str, result: Dict[str, Any], cache_dir: Optional[Path], model: str = "") -> None:
    if cache_dir is None:
        return
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = _cache_key(prompt, model)
    cache_file = cache_dir / f"{key}.json"
    try:
        with open(cache_file, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False)
    except Exception:
        pass


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
            return 1
        elif duration > 3.0:
            return 2
        elif duration > 1.0:
            return 4
        elif duration > 0.5:
            return 6
        else:
            return 8
    except Exception:
        return 1


def enhance_finding(
    record: Dict[str, Any],
    model: str = "llama3.2",
    timeout: int = 300,
    cache_dir: Optional[Path] = _DEFAULT_CACHE_DIR,
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
    cache_dir:
        Directory for on-disk LLM response cache.  Pass ``None`` to disable.
    """
    try:
        return _call_ollama(record, model=model, timeout=timeout, cache_dir=cache_dir)
    except Exception as exc:
        logger.warning(
            "Ollama enhancement failed for %s: %s - using heuristic-only data",
            record.get("finding_id", "unknown"),
            exc,
        )
        return record


def map_external_record(
    record: Dict[str, Any],
    model: str = "llama3.2",
    timeout: int = 300,
    cache_dir: Optional[Path] = _DEFAULT_CACHE_DIR,
) -> Optional[Dict[str, Any]]:
    """
    Semantic mapping mode: convert an external dataset record to the unified
    RedBlue schema fields using the Ollama LLM.

    Returns a dict with mapped fields or ``None`` on failure (caller should
    fall back to heuristic mapping).

    Parameters
    ----------
    record:
        Arbitrary dict from an external dataset.
    model:
        Ollama model name.
    timeout:
        HTTP timeout in seconds.
    cache_dir:
        Directory for on-disk LLM response cache.
    """
    try:
        return _call_ollama_mapping(record, model=model, timeout=timeout, cache_dir=cache_dir)
    except Exception as exc:
        logger.debug("Ollama semantic mapping failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_prompt(record: Dict[str, Any]) -> str:
    title = record.get("title") or "(no title)"
    description = record.get("description") or "(no description)"

    if len(description) > 1500:
        description = description[:1500] + "... [truncated]"

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


def _build_mapping_prompt(record: Dict[str, Any]) -> str:
    # Represent the external record as compact JSON, truncated for safety
    raw = json.dumps(record, ensure_ascii=False)
    if len(raw) > 2000:
        raw = raw[:2000] + "... [truncated]"

    return (
        "You are a cybersecurity data engineer mapping an external dataset record "
        "to a unified schema.\n"
        "Respond ONLY with a valid JSON object - no markdown fences, no explanation.\n\n"
        f"Few-shot examples:{_MAPPING_FEW_SHOT}\n"
        f"External record to map:\n{raw}\n\n"
        "Fill in this exact JSON structure:\n"
        f"{_MAPPING_SCHEMA}"
    )


def _parse_json_response(raw: str, finding_id: str = "unknown") -> Optional[Dict[str, Any]]:
    """
    Try to parse *raw* as JSON. Falls back to extracting the first
    ``{...}`` block if the model wraps output in markdown or prose.
    """
    raw = raw.strip()

    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
        raw = raw.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    logger.debug("Failed to parse Ollama response for %s. Raw: %r", finding_id, raw)
    return None


def _call_ollama_api(prompt: str, model: str, timeout: int) -> str:
    """Make a raw Ollama generate call and return the response string."""
    payload = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
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

    return body.get("response", "")


def _call_ollama(
    record: Dict[str, Any],
    model: str,
    timeout: int,
    cache_dir: Optional[Path],
) -> Dict[str, Any]:
    """Make the Ollama API call for validation/correction and merge back."""
    prompt = _build_prompt(record)

    cached = _load_cached(prompt, cache_dir, model)
    if cached is not None:
        enriched = cached
    else:
        raw_response = _call_ollama_api(prompt, model, timeout)
        enriched = _parse_json_response(raw_response, finding_id=record.get("finding_id", "unknown"))
        if enriched is None:
            logger.warning(
                "Could not parse Ollama JSON response for %s - keeping heuristic data",
                record.get("finding_id", "unknown"),
            )
            return record
        _save_cached(prompt, enriched, cache_dir, model)

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

    if enriched.get("remediation") and not merged.get("recommendation"):
        merged["recommendation"] = enriched["remediation"]

    quality = enriched.get("quality_score")
    if quality is not None:
        try:
            merged["quality_score"] = int(quality)
        except (TypeError, ValueError):
            pass

    return merged


def _call_ollama_mapping(
    record: Dict[str, Any],
    model: str,
    timeout: int,
    cache_dir: Optional[Path],
) -> Optional[Dict[str, Any]]:
    """Make the Ollama API call for semantic mapping of an external record."""
    prompt = _build_mapping_prompt(record)

    cached = _load_cached(prompt, cache_dir, model)
    if cached is not None:
        return cached

    raw_response = _call_ollama_api(prompt, model, timeout)
    result = _parse_json_response(raw_response)
    if result is not None:
        _save_cached(prompt, result, cache_dir, model)
    return result

