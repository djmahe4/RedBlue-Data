"""
benchmarks/rb5_dataset_stats.py

RB-5: Dataset Statistics & Coverage
=====================================
Task: Report aggregate statistics for a RedBlue dataset split.

Outputs a JSON summary with counts, label distributions, and coverage metrics
suitable for a dataset card or model-card comparison table.

Usage::

    python benchmarks/rb5_dataset_stats.py --all-splits
    python benchmarks/rb5_dataset_stats.py --split test
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from utils import read_jsonl


def _split_stats(findings: List[Dict[str, Any]], split_name: str) -> Dict[str, Any]:
    vuln_counts = Counter(r.get("vuln_type") for r in findings if r.get("vuln_type"))
    sev_counts = Counter(r.get("severity") for r in findings if r.get("severity"))
    vendor_counts = Counter(r.get("vendor") for r in findings if r.get("vendor"))
    has_rec = sum(1 for r in findings if r.get("recommendation"))
    has_desc = sum(1 for r in findings if r.get("description"))
    source_datasets = Counter(r.get("source_dataset") for r in findings if r.get("source_dataset"))

    return {
        "split": split_name,
        "total_findings": len(findings),
        "with_description": has_desc,
        "with_recommendation": has_rec,
        "unique_vuln_types": len(vuln_counts),
        "unique_vendors": len(vendor_counts),
        "vuln_type_distribution": dict(vuln_counts.most_common(20)),
        "severity_distribution": dict(sev_counts),
        "source_datasets": dict(source_datasets),
    }


def _all_splits_stats(dataset_dir: Path) -> Dict[str, Any]:
    summary: Dict[str, Any] = {}
    for split in ("train", "val", "test"):
        path = dataset_dir / split / "findings.jsonl"
        if path.exists():
            records = read_jsonl(path)
            summary[split] = _split_stats(records, split)
        else:
            summary[split] = {"split": split, "error": "not found"}

    # Raw totals
    raw_path = dataset_dir / "raw" / "findings.jsonl"
    if raw_path.exists():
        raw_records = read_jsonl(raw_path)
        summary["raw"] = _split_stats(raw_records, "raw")

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="RB-5: Dataset Statistics")
    parser.add_argument("--split", default=None, choices=["train", "val", "test", "raw"])
    parser.add_argument("--all-splits", action="store_true", default=False)
    parser.add_argument("--dataset-dir", type=Path, default=Path("dataset"))
    args = parser.parse_args()

    if args.all_splits:
        results = _all_splits_stats(args.dataset_dir)
    elif args.split:
        fname = "findings.jsonl"
        if args.split == "raw":
            path = args.dataset_dir / "raw" / fname
        else:
            path = args.dataset_dir / args.split / fname
        if not path.exists():
            print(f"[ERROR] {path} not found.", file=sys.stderr)
            sys.exit(1)
        records = read_jsonl(path)
        results = _split_stats(records, args.split)
    else:
        results = _all_splits_stats(args.dataset_dir)

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
