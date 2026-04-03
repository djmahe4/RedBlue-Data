"""
utils.py - Shared helper utilities: privacy masking, file I/O, hashing.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Dict

# ---------------------------------------------------------------------------
# Privacy masking patterns
# ---------------------------------------------------------------------------
_IP_PATTERN = re.compile(
    r"\b(?:\d{1,3}\.){3}\d{1,3}\b"
)
_EMAIL_PATTERN = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
)
# Simple credential patterns: "password: xxx", "token: xxx", "key: xxx"
_CRED_PATTERN = re.compile(
    r"(?i)(password|passwd|token|api[_\-]?key|secret|credential)[=:\s]+\S+",
)


def mask_sensitive(text: str) -> str:
    """Replace IPs, emails and credential-like strings with placeholders."""
    text = _IP_PATTERN.sub("[IP_REDACTED]", text)
    text = _EMAIL_PATTERN.sub("[EMAIL_REDACTED]", text)
    text = _CRED_PATTERN.sub(r"\1: [REDACTED]", text)
    return text


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------

def file_size_mb(path: Path) -> float:
    """Return file size in megabytes."""
    return path.stat().st_size / (1024 * 1024)


def compute_report_id(path: Path) -> str:
    """Stable SHA-256-based report identifier derived from the file path."""
    return hashlib.sha256(path.as_posix().encode()).hexdigest()[:16]


def ensure_dir(path: str | Path) -> Path:
    """Create directory (and parents) if it doesn't exist, return Path."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------------------
# JSONL helpers
# ---------------------------------------------------------------------------

def append_jsonl(record: Dict[str, Any], filepath: Path) -> None:
    """Append a single JSON record as a line to a JSONL file."""
    with open(filepath, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_jsonl(filepath: Path) -> list:
    """Read all records from a JSONL file."""
    records = []
    if not filepath.exists():
        return records
    with open(filepath, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------

def load_manifest(manifest_path: Path) -> Dict[str, Any]:
    """Load existing manifest or return a fresh one."""
    if manifest_path.exists():
        with open(manifest_path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    return {
        "processed_reports": [],
        "skipped_files": [],
        "total_findings": 0,
        "config_used": {},
    }


def save_manifest(manifest: Dict[str, Any], manifest_path: Path) -> None:
    """Persist the manifest as a formatted JSON file."""
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
