"""
schemas.py - Pydantic v2 models for all RedBlue dataset records.

All JSONL reads/writes are validated against these models to ensure
data integrity throughout the pipeline.
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

SEVERITY_LEVELS = Literal["critical", "high", "medium", "low", "info"]
SPLIT_TYPES = Literal["train", "val", "test"]


# ---------------------------------------------------------------------------
# Core finding record (findings.jsonl)
# ---------------------------------------------------------------------------

class Finding(BaseModel):
    """Structured representation of a single vulnerability finding."""

    report_id: str = Field(..., description="SHA-256-based identifier for the source report")
    finding_id: str = Field(..., description="Unique identifier: <report_id>_<index>")
    vendor: str = Field(default="unknown", description="Reporting firm / source vendor")
    source_file: str = Field(..., description="Posix-style path to source file")
    file_type: str = Field(default="unknown", description="File extension without dot")
    file_size_mb: float = Field(default=0.0, ge=0.0)

    exec_summary: Optional[str] = Field(default=None)
    title: Optional[str] = Field(default=None)
    description: Optional[str] = Field(default=None)
    technical_details: Optional[str] = Field(default=None)
    recommendation: Optional[str] = Field(default=None)

    vuln_type: Optional[str] = Field(default=None, description="Vulnerability category label")
    cwe: Optional[str] = Field(default=None, description="CWE identifier e.g. CWE-89")
    owasp: Optional[str] = Field(default=None, description="OWASP Top 10 category e.g. A03:2021")
    severity: Optional[SEVERITY_LEVELS] = Field(default=None)
    cvss_score: Optional[str] = Field(default=None, description="CVSS numeric score as string")

    # Optional Ollama-enriched fields
    enhanced_description: Optional[str] = Field(default=None)
    attack_vector: Optional[str] = Field(default=None)
    quality_score: Optional[int] = Field(default=None, ge=1, le=10)

    # For external-source records
    source_dataset: Optional[str] = Field(default=None, description="Name of external source dataset")
    split: Optional[SPLIT_TYPES] = Field(default=None)

    @field_validator("severity", mode="before")
    @classmethod
    def normalise_severity(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        s = str(v).lower().strip()
        if s == "informational":
            return "info"
        if s in ("critical", "high", "medium", "low", "info"):
            return s
        return None

    @field_validator("cwe", mode="before")
    @classmethod
    def normalise_cwe(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        s = str(v).strip()
        if s.lower() in ("unknown", ""):
            return None
        return s

    def to_jsonl_dict(self) -> Dict[str, Any]:
        """Return a plain dict suitable for JSONL serialization."""
        return self.model_dump(exclude_none=False)


# ---------------------------------------------------------------------------
# Instruction-tuning pair base
# ---------------------------------------------------------------------------

class InstructionPair(BaseModel):
    """Base class for instruction-tuning records."""

    instruction: str = Field(..., description="Task instruction for the LLM")
    input: str = Field(..., description="Context / question provided to the LLM")
    output: str = Field(..., description="Expected model output / answer")
    finding_id: str = Field(..., description="Back-reference to the originating finding")
    vuln_type: Optional[str] = Field(default=None)
    severity: Optional[SEVERITY_LEVELS] = Field(default=None)
    source_dataset: Optional[str] = Field(default=None)
    split: Optional[SPLIT_TYPES] = Field(default=None)

    @field_validator("severity", mode="before")
    @classmethod
    def normalise_severity(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        s = str(v).lower().strip()
        if s == "informational":
            return "info"
        if s in ("critical", "high", "medium", "low", "info"):
            return s
        return None

    def to_jsonl_dict(self) -> Dict[str, Any]:
        return self.model_dump(exclude_none=False)


# ---------------------------------------------------------------------------
# Red-team and blue-team pair specialisations
# ---------------------------------------------------------------------------

class RedTeamPair(InstructionPair):
    """Offensive / red-team instruction-tuning record."""

    instruction: str = Field(
        default="Generate a detailed exploit or attack scenario for the following vulnerability.",
        description="Offensive task instruction",
    )


class BlueTeamPair(InstructionPair):
    """Defensive / blue-team instruction-tuning record."""

    instruction: str = Field(
        default="Provide a secure fix and remediation guidance for the following vulnerability.",
        description="Defensive task instruction",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def finding_from_dict(data: Dict[str, Any]) -> Finding:
    """Validate and construct a :class:`Finding` from an arbitrary dict."""
    return Finding.model_validate(data)


def red_team_from_dict(data: Dict[str, Any]) -> RedTeamPair:
    return RedTeamPair.model_validate(data)


def blue_team_from_dict(data: Dict[str, Any]) -> BlueTeamPair:
    return BlueTeamPair.model_validate(data)


def validated_finding_dicts(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Validate a list of raw dicts through the Finding schema; skip invalid ones."""
    out = []
    for r in records:
        try:
            out.append(finding_from_dict(r).to_jsonl_dict())
        except Exception:
            pass
    return out
