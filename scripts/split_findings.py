"""
split_findings.py - Extract individual structured findings from a findings block.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

# A finding can start with:
#   "Finding 1", "Finding #1", "Issue 2", "Vulnerability 3"
#   or a severity keyword followed by a colon, e.g. "High: Reflected XSS"
_FINDING_HEADER_RE = re.compile(
    r"(?i)^(?:finding|vulnerability|vulnerabilities|vuln|issue)\s*[#:]?\s*\d*\s*[:\-–]?\s*(.+)?$"
    r"|^(?:critical|high|medium|low|info)\s*[:\-–]\s*(.+)$",
    re.MULTILINE,
)

_SEVERITY_LINE_RE = re.compile(
    r"(?i)\b(severity|risk|cvss)[:\s]+([^\n]+)"
)
_TITLE_CLEANUP_RE = re.compile(r"[^a-zA-Z0-9\s\-_]")


def _extract_title(header_match: re.Match) -> str:
    """Pull the first non-None capture group from the header match."""
    title = next((g for g in header_match.groups() if g), "")
    return title.strip()


def split_findings(findings_text: str) -> List[Dict[str, Optional[str]]]:
    """
    Parse a block of text containing multiple findings and return a list
    of structured dicts with keys: title, description, technical_details,
    recommendation.
    """
    if not findings_text.strip():
        return []

    # Split into chunks at each finding header
    splits = list(_FINDING_HEADER_RE.finditer(findings_text))
    if not splits:
        # No structured headers - treat the whole block as one finding
        return [_build_finding("Finding", findings_text)]

    findings: List[Dict[str, Optional[str]]] = []
    for i, match in enumerate(splits):
        title = _extract_title(match)
        start = match.end()
        end = splits[i + 1].start() if i + 1 < len(splits) else len(findings_text)
        body = findings_text[start:end].strip()
        findings.append(_build_finding(title or f"Finding {i + 1}", body))

    return findings


def _build_finding(title: str, body: str) -> Dict[str, Optional[str]]:
    """Build a structured finding dict from a title and body text."""
    lines = body.splitlines()

    # First non-empty lines → description; rest → technical_details
    description_lines: List[str] = []
    tech_lines: List[str] = []
    recommendation_lines: List[str] = []
    in_recommendation = False

    for line in lines:
        lower = line.lower()
        if re.search(r"\b(recommend|remediat|fix|mitigat)", lower):
            in_recommendation = True
        if in_recommendation:
            recommendation_lines.append(line)
        elif len(description_lines) < 5:
            description_lines.append(line)
        else:
            tech_lines.append(line)

    return {
        "title": title.strip(),
        "description": "\n".join(description_lines).strip() or None,
        "technical_details": "\n".join(tech_lines).strip() or None,
        "recommendation": "\n".join(recommendation_lines).strip() or None,
    }
