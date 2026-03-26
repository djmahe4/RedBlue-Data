"""
process_reports.py - Main orchestration script for the RedBlue dataset pipeline.

Usage:
    python scripts/process_reports.py [options]

Options are documented in scripts/config.py / --help.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

# Allow imports from the scripts directory when run directly
sys.path.insert(0, str(Path(__file__).parent))

from config import Config, get_config
from extract_text import extract_text
from heuristics import classify_finding
from segment_report import segment_report
from split_findings import split_findings
from utils import (
    append_jsonl,
    compute_report_id,
    ensure_dir,
    file_size_mb,
    load_manifest,
    mask_sensitive,
    save_manifest,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Scanning helpers
# ---------------------------------------------------------------------------

def _find_report_files(source_dir: Path, cfg: Config) -> list[Path]:
    """
    Walk *source_dir*, treating each immediate sub-directory as a vendor.
    Return all files whose extension is in cfg.allowed_extensions and whose
    size is within cfg.max_file_size_mb.
    """
    allowed = {ext.lower() for ext in cfg.allowed_extensions}
    candidates: list[Path] = []

    for item in sorted(source_dir.iterdir()):
        if not item.is_dir():
            continue
        for fpath in sorted(item.rglob("*")):
            if not fpath.is_file():
                continue
            if fpath.suffix.lower().lstrip(".") not in allowed:
                continue
            candidates.append(fpath)

    return candidates


def _get_vendor(path: Path, source_dir: Path) -> str:
    """Return the vendor name (first directory level inside source_dir)."""
    try:
        relative = path.relative_to(source_dir)
        return relative.parts[0] if relative.parts else "unknown"
    except ValueError:
        return "unknown"


# ---------------------------------------------------------------------------
# Per-report processing
# ---------------------------------------------------------------------------

def process_report(
    fpath: Path,
    source_dir: Path,
    cfg: Config,
) -> list[dict]:
    """
    Extract text, segment, split into findings, classify, and return a list
    of structured finding records.
    """
    vendor = _get_vendor(fpath, source_dir)
    report_id = compute_report_id(fpath)
    size_mb = file_size_mb(fpath)

    if size_mb > cfg.max_file_size_mb:
        logger.info("Skipping %s (%.2f MB > %.2f MB limit)", fpath.name, size_mb, cfg.max_file_size_mb)
        return []

    logger.info("Processing %s / %s (%.2f MB)", vendor, fpath.name, size_mb)
    raw_text = extract_text(fpath)
    if not raw_text.strip():
        logger.warning("No text extracted from %s", fpath)
        return []

    text = mask_sensitive(raw_text)
    segments = segment_report(text)
    findings = split_findings(segments["findings_raw"])

    records = []
    for idx, finding in enumerate(findings):
        classification = classify_finding(
            " ".join(filter(None, [finding.get("title"), finding.get("description")]))
        )
        record = {
            "report_id": report_id,
            "finding_id": f"{report_id}_{idx:04d}",
            "vendor": vendor,
            "source_file": str(fpath),
            "file_type": fpath.suffix.lower().lstrip("."),
            "file_size_mb": round(size_mb, 4),
            "exec_summary": segments.get("exec_summary") or None,
            "title": finding.get("title"),
            "description": finding.get("description"),
            "technical_details": finding.get("technical_details"),
            "recommendation": finding.get("recommendation"),
            **classification,
        }
        records.append(record)

    return records


# ---------------------------------------------------------------------------
# Dataset writers
# ---------------------------------------------------------------------------

def _write_finding(record: dict, findings_path: Path, red_path: Path, blue_path: Path) -> None:
    append_jsonl(record, findings_path)

    title = record.get("title") or ""
    description = record.get("description") or ""
    tech = record.get("technical_details") or ""
    recommendation = record.get("recommendation") or ""

    if title or description:
        red_record = {
            "instruction": "Generate a detailed exploit or attack scenario for the following vulnerability.",
            "input": f"Title: {title}\nDescription: {description}",
            "output": tech or description,
            "finding_id": record["finding_id"],
            "vuln_type": record.get("vuln_type"),
            "severity": record.get("severity"),
        }
        append_jsonl(red_record, red_path)

        blue_record = {
            "instruction": "Provide a secure fix and remediation guidance for the following vulnerability.",
            "input": f"Title: {title}\nDescription: {description}",
            "output": recommendation or "No specific recommendation provided.",
            "finding_id": record["finding_id"],
            "vuln_type": record.get("vuln_type"),
            "severity": record.get("severity"),
        }
        append_jsonl(blue_record, blue_path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    cfg = get_config()
    cfg.print_config()

    out_dir = ensure_dir(cfg.output_dir)
    findings_path = out_dir / "findings.jsonl"
    red_path = out_dir / "red_team.jsonl"
    blue_path = out_dir / "blue_team.jsonl"
    manifest_path = out_dir / "manifest.json"
    stats_path = out_dir / "stats.json"

    manifest = load_manifest(manifest_path) if cfg.incremental else {
        "processed_reports": [],
        "skipped_files": [],
        "total_findings": 0,
        "config_used": {},
    }

    # When NOT incremental, wipe existing outputs
    if not cfg.incremental:
        for p in (findings_path, red_path, blue_path):
            if p.exists():
                p.unlink()

    processed_ids: set[str] = set(manifest["processed_reports"])

    source_dir = Path("reports-source")
    if not source_dir.exists():
        logger.error(
            "Source directory 'reports-source' not found. "
            "Clone it first:\n  git clone --depth 1 %s reports-source",
            cfg.source_repo,
        )
        sys.exit(1)

    candidates = _find_report_files(source_dir, cfg)
    logger.info("Found %d candidate report files", len(candidates))

    reports_processed = 0
    total_findings = manifest.get("total_findings", 0)
    max_r = len(candidates) if cfg.full_run else cfg.max_reports

    for fpath in candidates:
        if reports_processed >= max_r:
            logger.info("Reached max_reports limit (%d)", max_r)
            break

        report_id = compute_report_id(fpath)
        if report_id in processed_ids:
            logger.debug("Skipping already-processed report: %s", fpath.name)
            continue

        size_mb = file_size_mb(fpath)
        if size_mb > cfg.max_file_size_mb:
            manifest["skipped_files"].append(str(fpath))
            continue

        records = process_report(fpath, source_dir, cfg)
        if not records:
            manifest["skipped_files"].append(str(fpath))
            continue

        for rec in records:
            _write_finding(rec, findings_path, red_path, blue_path)

        total_findings += len(records)
        processed_ids.add(report_id)
        manifest["processed_reports"].append(report_id)
        reports_processed += 1

    manifest["total_findings"] = total_findings
    manifest["config_used"] = cfg.as_dict()
    save_manifest(manifest, manifest_path)

    stats = {
        "reports_processed_this_run": reports_processed,
        "total_reports_ever": len(manifest["processed_reports"]),
        "total_findings": total_findings,
        "skipped_files": len(manifest["skipped_files"]),
    }
    with open(stats_path, "w", encoding="utf-8") as fh:
        json.dump(stats, fh, indent=2)

    logger.info(
        "Done - processed %d reports, %d findings total.",
        reports_processed,
        total_findings,
    )
    logger.info("Stats: %s", json.dumps(stats))


if __name__ == "__main__":
    main()
