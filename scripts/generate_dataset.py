"""
generate_dataset.py - Full dataset generation with train/val/test splits.

Command: python scripts/generate_dataset.py [options]

This orchestrator:
1. Processes all reports from ``reports-source/`` (uses existing pipeline logic).
2. Optionally merges external datasets from ``external_datasets/``.
3. Optionally uses Ollama for semantic enrichment.
4. Creates stratified train/val/test splits (default 80/10/10).
5. Outputs files under dataset/ in the structure::

    dataset/
    ├── raw/         findings.jsonl, red_team.jsonl, blue_team.jsonl
    ├── train/       findings.jsonl, red_team.jsonl, blue_team.jsonl
    ├── val/         findings.jsonl, red_team.jsonl, blue_team.jsonl
    └── test/        findings.jsonl, red_team.jsonl, blue_team.jsonl

Example commands::

    # Basic
    python scripts/generate_dataset.py --max-reports 100

    # With external merge + Ollama
    python scripts/generate_dataset.py --merge-external --use-ollama --ollama-model llama3.2

    # With splits and push to hub
    python scripts/generate_dataset.py --split-ratios 0.8 0.1 0.1 --push-to-hub myuser/redblue-data
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).parent))

from config import Config
from extract_text import extract_text
from heuristics import classify_finding
from schemas import Finding, RedTeamPair, BlueTeamPair
from segment_report import segment_report
from split_findings import split_findings
from utils import (
    JSONLWriter,
    compute_report_id,
    ensure_dir,
    file_size_mb,
    load_manifest,
    mask_sensitive,
    read_jsonl,
    save_manifest,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Report scanning (mirrors process_reports.py logic)
# ---------------------------------------------------------------------------

def _find_report_files(source_dir: Path, cfg: "GenerateConfig") -> List[Path]:
    allowed = {ext.lower() for ext in cfg.allowed_extensions}
    candidates: List[Path] = []
    for item in sorted(source_dir.iterdir()):
        if not item.is_dir():
            continue
        for fpath in sorted(item.rglob("*")):
            if fpath.is_file() and fpath.suffix.lower().lstrip(".") in allowed:
                candidates.append(fpath)
    return candidates


def _get_vendor(path: Path, source_dir: Path) -> str:
    try:
        relative = path.relative_to(source_dir)
        return relative.parts[0] if relative.parts else "unknown"
    except ValueError:
        return "unknown"


def _process_report(
    fpath: Path,
    source_dir: Path,
    cfg: "GenerateConfig",
    ollama_enhance=None,
) -> List[Dict[str, Any]]:
    vendor = _get_vendor(fpath, source_dir)
    report_id = compute_report_id(fpath)
    size_mb = file_size_mb(fpath)

    if size_mb > cfg.max_file_size_mb:
        return []

    raw_text = extract_text(fpath, skip_ocr=cfg.skip_ocr)
    if not raw_text.strip():
        return []

    if len(raw_text.split()) < cfg.min_words:
        return []

    text = mask_sensitive(raw_text)
    segments = segment_report(text)
    findings_raw = split_findings(segments["findings_raw"])

    records: List[Dict[str, Any]] = []
    for idx, finding in enumerate(findings_raw):
        classification = classify_finding(
            " ".join(filter(None, [finding.get("title"), finding.get("description")]))
        )
        record = {
            "report_id": report_id,
            "finding_id": f"{report_id}_{idx:04d}",
            "vendor": vendor,
            "source_file": fpath.as_posix(),
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

    if ollama_enhance is not None and records:
        from concurrent.futures import ThreadPoolExecutor
        from ollama_enhancer import get_recommended_workers
        max_workers = get_recommended_workers(cfg.ollama_model)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(ollama_enhance, rec, model=cfg.ollama_model) for rec in records]
            records = [f.result() for f in futures]

    return records


def _record_to_pairs(record: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    title = record.get("title") or ""
    description = record.get("description") or ""
    tech = record.get("technical_details") or ""
    recommendation = record.get("recommendation") or ""

    if not (title or description):
        return None, None

    red = {
        "instruction": "Generate a detailed exploit or attack scenario for the following vulnerability.",
        "input": f"Title: {title}\nDescription: {description}",
        "output": tech or description,
        "finding_id": record["finding_id"],
        "vuln_type": record.get("vuln_type"),
        "severity": record.get("severity"),
    }
    blue = {
        "instruction": "Provide a secure fix and remediation guidance for the following vulnerability.",
        "input": f"Title: {title}\nDescription: {description}",
        "output": recommendation or "No specific recommendation provided.",
        "finding_id": record["finding_id"],
        "vuln_type": record.get("vuln_type"),
        "severity": record.get("severity"),
    }
    return red, blue


# ---------------------------------------------------------------------------
# Stratified splitting
# ---------------------------------------------------------------------------

def _stratify_key(record: Dict[str, Any]) -> str:
    """Return a stratification key based on vuln_type and severity."""
    vt = record.get("vuln_type") or "unknown"
    sev = record.get("severity") or "unknown"
    return f"{vt}|{sev}"


def _stratified_split(
    records: List[Dict[str, Any]],
    train_ratio: float,
    val_ratio: float,
    seed: int = 42,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Stratified train/val/test split.

    Buckets records by (vuln_type, severity) then splits each bucket
    proportionally.  Falls back to a random split for small buckets.
    """
    random.seed(seed)

    # Group by stratum
    buckets: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in records:
        buckets[_stratify_key(r)].append(r)

    train, val, test = [], [], []
    for stratum, items in buckets.items():
        random.shuffle(items)
        n = len(items)
        n_train = max(1, round(n * train_ratio))
        n_val = max(0, round(n * val_ratio))
        n_test = max(0, n - n_train - n_val)

        train.extend(items[:n_train])
        val.extend(items[n_train: n_train + n_val])
        test.extend(items[n_train + n_val: n_train + n_val + n_test])

    # Shuffle final splits
    random.shuffle(train)
    random.shuffle(val)
    random.shuffle(test)

    return train, val, test


def _assign_splits(
    records: List[Dict[str, Any]],
    train_ratio: float,
    val_ratio: float,
) -> Dict[str, List[Dict[str, Any]]]:
    train, val, test = _stratified_split(records, train_ratio, val_ratio)
    for r in train:
        r["split"] = "train"
    for r in val:
        r["split"] = "val"
    for r in test:
        r["split"] = "test"
    return {"train": train, "val": val, "test": test}


# ---------------------------------------------------------------------------
# Dataset writing helpers
# ---------------------------------------------------------------------------

def _write_split(
    split_name: str,
    findings: List[Dict[str, Any]],
    red_pairs: List[Dict[str, Any]],
    blue_pairs: List[Dict[str, Any]],
    base_dir: Path,
) -> None:
    split_dir = base_dir / split_name
    split_dir.mkdir(parents=True, exist_ok=True)

    finding_ids = {r["finding_id"] for r in findings}

    with (
        JSONLWriter(split_dir / "findings.jsonl", mode="w") as fw,
        JSONLWriter(split_dir / "red_team.jsonl", mode="w") as rw,
        JSONLWriter(split_dir / "blue_team.jsonl", mode="w") as bw,
    ):
        for r in findings:
            fw.write(r)
        for r in red_pairs:
            if r.get("finding_id") in finding_ids:
                rw.write(r)
        for r in blue_pairs:
            if r.get("finding_id") in finding_ids:
                bw.write(r)


# ---------------------------------------------------------------------------
# Hugging Face Hub push
# ---------------------------------------------------------------------------

def _push_to_hub(dataset_dir: Path, repo_id: str) -> None:
    """Push all split directories to Hugging Face Hub as a dataset repo."""
    try:
        from huggingface_hub import HfApi, upload_folder  # type: ignore
    except ImportError:
        logger.error(
            "huggingface_hub is not installed. "
            "Run: pip install huggingface_hub[hf_transfer]"
        )
        return

    api = HfApi()
    try:
        api.create_repo(repo_id=repo_id, repo_type="dataset", exist_ok=True)
    except Exception as exc:
        logger.error("Failed to create/locate HF repo %s: %s", repo_id, exc)
        return

    upload_folder(
        repo_id=repo_id,
        repo_type="dataset",
        folder_path=str(dataset_dir),
        commit_message="Upload RedBlue dataset",
    )
    logger.info("Dataset pushed to https://huggingface.co/datasets/%s", repo_id)


# ---------------------------------------------------------------------------
# Configuration for this script
# ---------------------------------------------------------------------------

class GenerateConfig:
    def __init__(
        self,
        max_reports: Optional[int],
        max_file_size_mb: float,
        allowed_extensions: List[str],
        skip_ocr: bool,
        min_words: int,
        use_ollama: bool,
        ollama_model: str,
        merge_external: bool,
        external_dir: Path,
        output_dir: Path,
        train_ratio: float,
        val_ratio: float,
        push_to_hub: Optional[str],
        reset: bool,
        dedup_threshold: float,
        max_per_source: Optional[int],
        seed: int,
    ) -> None:
        self.max_reports = max_reports
        self.max_file_size_mb = max_file_size_mb
        self.allowed_extensions = allowed_extensions
        self.skip_ocr = skip_ocr
        self.min_words = min_words
        self.use_ollama = use_ollama
        self.ollama_model = ollama_model
        self.merge_external = merge_external
        self.external_dir = external_dir
        self.output_dir = output_dir
        self.train_ratio = train_ratio
        self.val_ratio = val_ratio
        self.push_to_hub = push_to_hub
        self.reset = reset
        self.dedup_threshold = dedup_threshold
        self.max_per_source = max_per_source
        self.seed = seed


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a full RedBlue cybersecurity instruction-tuning dataset",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--max-reports", type=int, default=None,
                        help="Max reports to process (default: all)")
    parser.add_argument("--max-file-size-mb", type=float, default=5.0,
                        help="Max PDF/file size in MB")
    parser.add_argument("--allowed-extensions", type=str, default="pdf,md,html,docx",
                        help="Comma-separated allowed file extensions")
    parser.add_argument("--skip-ocr", action="store_true", default=False)
    parser.add_argument("--min-words", type=int, default=20,
                        help="Minimum word count for extracted text")
    parser.add_argument("--use-ollama", action="store_true", default=False,
                        help="Enable Ollama for semantic enrichment")
    parser.add_argument("--ollama-model", type=str, default="llama3.2")
    parser.add_argument("--merge-external", action="store_true", default=False,
                        help="Merge external datasets from external_datasets/")
    parser.add_argument("--external-dir", type=Path, default=Path("external_datasets"),
                        help="Root directory of external datasets")
    parser.add_argument("--output-dir", type=Path, default=Path("dataset"),
                        help="Root output directory")
    parser.add_argument("--split-ratios", type=float, nargs=3, default=[0.8, 0.1, 0.1],
                        metavar=("TRAIN", "VAL", "TEST"),
                        help="Train/val/test split ratios (must sum to 1)")
    parser.add_argument("--push-to-hub", type=str, default=None, metavar="USER/REPO",
                        help="Push dataset to Hugging Face Hub (e.g. myuser/redblue-data)")
    parser.add_argument("--reset", action="store_true", default=False,
                        help="Wipe and regenerate all outputs")
    parser.add_argument("--dedup-threshold", type=float, default=0.92,
                        help="TF-IDF deduplication threshold for external records")
    parser.add_argument("--max-per-source", type=int, default=None,
                        help="Max records per external source file")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for splits")
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> None:
    args = _parse_args(argv)

    train_ratio, val_ratio, test_ratio = args.split_ratios
    if abs(train_ratio + val_ratio + test_ratio - 1.0) > 1e-6:
        logger.error("Split ratios must sum to 1.0 (got %.4f)", train_ratio + val_ratio + test_ratio)
        sys.exit(1)

    exts = [e.strip().lstrip(".").lower() for e in args.allowed_extensions.split(",") if e.strip()]
    cfg = GenerateConfig(
        max_reports=args.max_reports,
        max_file_size_mb=args.max_file_size_mb,
        allowed_extensions=exts,
        skip_ocr=args.skip_ocr,
        min_words=args.min_words,
        use_ollama=args.use_ollama,
        ollama_model=args.ollama_model,
        merge_external=args.merge_external,
        external_dir=args.external_dir,
        output_dir=args.output_dir,
        train_ratio=train_ratio,
        val_ratio=val_ratio,
        push_to_hub=args.push_to_hub,
        reset=args.reset,
        dedup_threshold=args.dedup_threshold,
        max_per_source=args.max_per_source,
        seed=args.seed,
    )

    raw_dir = cfg.output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = cfg.output_dir / "manifest.json"
    stats_path = cfg.output_dir / "stats.json"

    # Reset existing outputs if requested
    if cfg.reset:
        for subdir in ("raw", "train", "val", "test"):
            d = cfg.output_dir / subdir
            if d.exists():
                for f in d.iterdir():
                    if f.is_file():
                        f.unlink()
        for p in (manifest_path, stats_path):
            if p.exists():
                p.unlink()

    manifest = load_manifest(manifest_path)
    processed_ids: set = set(manifest["processed_reports"])

    # --- Step 1: Process internal reports ---
    source_dir = Path("reports-source")
    if not source_dir.exists():
        logger.error(
            "Source directory 'reports-source' not found. "
            "Clone it first: git clone --depth 1 "
            "https://github.com/juliocesarfort/public-pentesting-reports reports-source"
        )
        sys.exit(1)

    ollama_enhance = None
    if cfg.use_ollama:
        from ollama_enhancer import check_ollama_available, enhance_finding
        if check_ollama_available(cfg.ollama_model):
            ollama_enhance = enhance_finding
            logger.info("Ollama enrichment enabled (model: %s)", cfg.ollama_model)
        else:
            logger.warning("Ollama unavailable – continuing without enrichment")

    candidates = _find_report_files(source_dir, cfg)
    logger.info("Found %d candidate report files", len(candidates))

    max_r = len(candidates) if cfg.max_reports is None else cfg.max_reports
    reports_processed = 0
    all_findings: List[Dict[str, Any]] = []
    all_red: List[Dict[str, Any]] = []
    all_blue: List[Dict[str, Any]] = []

    with (
        JSONLWriter(raw_dir / "findings.jsonl") as fw,
        JSONLWriter(raw_dir / "red_team.jsonl") as rw,
        JSONLWriter(raw_dir / "blue_team.jsonl") as bw,
    ):
        for fpath in tqdm(candidates, desc="Processing reports"):
            if reports_processed >= max_r:
                logger.info("Reached max-reports limit (%d)", max_r)
                break

            report_id = compute_report_id(fpath)
            if report_id in processed_ids:
                continue

            size_mb = file_size_mb(fpath)
            if size_mb > cfg.max_file_size_mb:
                manifest["skipped_files"].append(fpath.as_posix())
                continue

            records = _process_report(fpath, source_dir, cfg, ollama_enhance)
            if not records:
                manifest["skipped_files"].append(fpath.as_posix())
                continue

            for rec in records:
                fw.write(rec)
                red, blue = _record_to_pairs(rec)
                if red:
                    rw.write(red)
                    all_red.append(red)
                if blue:
                    bw.write(blue)
                    all_blue.append(blue)
                all_findings.append(rec)

            manifest["processed_reports"].append(report_id)
            processed_ids.add(report_id)
            reports_processed += 1

    manifest["total_findings"] = len(all_findings)
    save_manifest(manifest, manifest_path)
    logger.info("Internal reports: %d processed, %d findings", reports_processed, len(all_findings))

    # --- Step 2: Merge external datasets ---
    ext_findings: List[Dict[str, Any]] = []
    ext_red: List[Dict[str, Any]] = []
    ext_blue: List[Dict[str, Any]] = []

    if cfg.merge_external:
        from merge_external import merge_external_datasets
        ext_findings, ext_red, ext_blue = merge_external_datasets(
            external_dir=cfg.external_dir,
            output_dir=raw_dir,
            use_ollama=cfg.use_ollama,
            ollama_model=cfg.ollama_model,
            dedup_threshold=cfg.dedup_threshold,
            existing_findings=all_findings,
            max_per_source=cfg.max_per_source,
        )
        all_findings.extend(ext_findings)
        all_red.extend(ext_red)
        all_blue.extend(ext_blue)

    logger.info(
        "Total dataset: %d findings, %d red-team, %d blue-team pairs",
        len(all_findings),
        len(all_red),
        len(all_blue),
    )

    if not all_findings:
        logger.warning("No findings produced – skipping splits and stats")
        return

    # --- Step 3: Stratified splits ---
    finding_splits = _assign_splits(all_findings, cfg.train_ratio, cfg.val_ratio)

    # Build finding_id → split mapping for red/blue alignment
    id_to_split: Dict[str, str] = {}
    for split_name, recs in finding_splits.items():
        for r in recs:
            id_to_split[r["finding_id"]] = split_name

    for r in all_red:
        r["split"] = id_to_split.get(r.get("finding_id", ""), "train")
    for r in all_blue:
        r["split"] = id_to_split.get(r.get("finding_id", ""), "train")

    red_splits: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    blue_splits: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in all_red:
        red_splits[r["split"]].append(r)
    for r in all_blue:
        blue_splits[r["split"]].append(r)

    for split_name in ("train", "val", "test"):
        _write_split(
            split_name,
            finding_splits[split_name],
            red_splits[split_name],
            blue_splits[split_name],
            cfg.output_dir,
        )
        logger.info(
            "Split %-5s: %d findings, %d red, %d blue",
            split_name,
            len(finding_splits[split_name]),
            len(red_splits[split_name]),
            len(blue_splits[split_name]),
        )

    # --- Step 4: Save stats ---
    stats = {
        "total_findings": len(all_findings),
        "internal_findings": len(all_findings) - len(ext_findings),
        "external_findings": len(ext_findings),
        "red_team_pairs": len(all_red),
        "blue_team_pairs": len(all_blue),
        "splits": {
            s: len(v) for s, v in finding_splits.items()
        },
        "split_ratios": {
            "train": cfg.train_ratio,
            "val": cfg.val_ratio,
            "test": round(1.0 - cfg.train_ratio - cfg.val_ratio, 4),
        },
    }
    with open(stats_path, "w", encoding="utf-8") as fh:
        json.dump(stats, fh, indent=2)
    logger.info("Stats: %s", json.dumps(stats))

    # --- Step 5: (Optional) Push to Hub ---
    if cfg.push_to_hub:
        _push_to_hub(cfg.output_dir, cfg.push_to_hub)


if __name__ == "__main__":
    main()
