"""
heuristics.py - Map findings text to vulnerability type, CWE, and OWASP category.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# (pattern, vuln_type, cwe, owasp)
# ---------------------------------------------------------------------------
_RULES: List[Tuple[re.Pattern, str, str, str]] = [
    (re.compile(r"\bSQL\s*i(njection)?\b", re.I), "SQLi", "CWE-89", "A03:2021"),
    (re.compile(r"\bXSS\b|cross[\s\-]?site\s+script", re.I), "XSS", "CWE-79", "A03:2021"),
    (re.compile(r"\bRCE\b|remote\s+code\s+exec", re.I), "RCE", "CWE-78", "A03:2021"),
    (re.compile(r"\bIDOR\b|insecure\s+direct\s+object", re.I), "IDOR", "CWE-639", "A01:2021"),
    (re.compile(r"\bXXE\b|xml\s+external\s+entity", re.I), "XXE", "CWE-611", "A05:2021"),
    (re.compile(r"\bSSRF\b|server[\s\-]?side\s+request\s+forg", re.I), "SSRF", "CWE-918", "A10:2021"),
    (re.compile(r"\bCSRF\b|cross[\s\-]?site\s+request\s+forg", re.I), "CSRF", "CWE-352", "A01:2021"),
    (re.compile(r"\bpath\s+trav(ersal)?\b|directory\s+trav(ersal)?", re.I), "PathTraversal", "CWE-22", "A01:2021"),
    (re.compile(r"\bopen\s+redirect\b", re.I), "OpenRedirect", "CWE-601", "A01:2021"),
    (re.compile(r"\bbuffer\s+over(flow|run)\b", re.I), "BufferOverflow", "CWE-120", "A06:2021"),
    (re.compile(r"\bcommand\s+inject(ion)?\b", re.I), "CmdInjection", "CWE-77", "A03:2021"),
    (re.compile(r"\bLDAP\s+inject(ion)?\b", re.I), "LDAPInjection", "CWE-90", "A03:2021"),
    (re.compile(r"\bdeserialization\b", re.I), "Deserialization", "CWE-502", "A08:2021"),
    (re.compile(r"\bbroken\s+auth(entication)?\b", re.I), "BrokenAuth", "CWE-287", "A07:2021"),
    (re.compile(r"\bprivilege\s+escal(ation)?\b", re.I), "PrivEsc", "CWE-269", "A01:2021"),
    (re.compile(r"\binformation\s+disc?los(ure|ure)\b", re.I), "InfoDisclosure", "CWE-200", "A02:2021"),
    (re.compile(r"\bhard[\s\-]?coded\s+(cred|password|secret|key)\b", re.I), "HardcodedCreds", "CWE-798", "A02:2021"),
    (re.compile(r"\bweak\s+(crypto|cipher|hash|encryption)\b", re.I), "WeakCrypto", "CWE-327", "A02:2021"),
    (re.compile(r"\binsecure\s+deserialization\b", re.I), "Deserialization", "CWE-502", "A08:2021"),
    (re.compile(r"\bmissing\s+(authentication|authorization)\b", re.I), "MissingAuth", "CWE-306", "A07:2021"),
    (re.compile(r"\bcve[\s\-]\d{4}[\s\-]\d+\b", re.I), "KnownCVE", "CWE-1035", "A06:2021"),
]

_SEVERITY_PATTERN = re.compile(
    r"\b(critical|high|medium|low|info|informational)\b", re.I
)
_CVSS_PATTERN = re.compile(
    r"\bCVSS\s*(?:v\d)?(?:\s*score)?[:=\s]+(\d+(?:\.\d+)?)\b", re.I
)


def classify_finding(text: str) -> Dict[str, Optional[str]]:
    """
    Return vuln_type, cwe, owasp, severity and cvss_score for the given text.
    First matching rule wins for classification.
    """
    vuln_type: Optional[str] = None
    cwe: Optional[str] = None
    owasp: Optional[str] = None

    for pattern, vt, cwe_id, owasp_cat in _RULES:
        if pattern.search(text):
            vuln_type = vt
            cwe = cwe_id
            owasp = owasp_cat
            break

    severity_match = _SEVERITY_PATTERN.search(text)
    severity = severity_match.group(1).lower() if severity_match else None
    if severity == "informational":
        severity = "info"

    cvss_match = _CVSS_PATTERN.search(text)
    cvss_score = cvss_match.group(1) if cvss_match else None

    return {
        "vuln_type": vuln_type,
        "cwe": cwe,
        "owasp": owasp,
        "severity": severity,
        "cvss_score": cvss_score,
    }
