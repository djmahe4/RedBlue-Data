"""
segment_report.py - Split raw report text into logical sections.
"""
from __future__ import annotations

import re
from typing import Dict

# Patterns that mark the start of each section (case-insensitive)
_EXEC_SUMMARY_RE = re.compile(
    r"(?i)(executive\s+summary|management\s+summary|overview)",
)
_FINDINGS_RE = re.compile(
    r"(?i)(findings?|vulnerabilities|issues|results)",
)
_RECOMMENDATIONS_RE = re.compile(
    r"(?i)(recommendations?|remediation|mitigat|conclusions?)",
)

_SECTION_BREAK_RE = re.compile(r"\n{3,}")


def segment_report(text: str) -> Dict[str, str]:
    """
    Attempt to segment a report into exec_summary, findings_raw, and
    recommendations.  Falls back to returning the full text under
    findings_raw when no structural cues are found.
    """
    lines = text.splitlines()
    sections: Dict[str, list] = {
        "exec_summary": [],
        "findings_raw": [],
        "recommendations": [],
    }
    current: str = "findings_raw"  # default bucket

    for line in lines:
        stripped = line.strip()
        if _EXEC_SUMMARY_RE.match(stripped):
            current = "exec_summary"
        elif _FINDINGS_RE.match(stripped):
            current = "findings_raw"
        elif _RECOMMENDATIONS_RE.match(stripped):
            current = "recommendations"
        else:
            sections[current].append(line)

    return {k: "\n".join(v).strip() for k, v in sections.items()}
