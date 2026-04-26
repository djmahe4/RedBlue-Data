"""
benchmarks/rb1_vuln_classification.py

RB-1: Vulnerability Classification
===================================
Task: Given a finding description, predict the vulnerability type (e.g. SQLi, XSS, RCE).

Metric: Accuracy (exact match) and macro-F1 over all vuln_type labels.

Usage::

    python benchmarks/rb1_vuln_classification.py --split test

Expected dataset layout::

    dataset/test/findings.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from utils import read_jsonl


def _predict_heuristic(text: str) -> Optional[str]:
    from heuristics import classify_finding
    return classify_finding(text)["vuln_type"]


def evaluate(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Evaluate heuristic baseline on RB-1 task."""
    correct = 0
    total = 0
    per_class: Dict[str, Dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})

    for rec in records:
        gold = rec.get("vuln_type")
        if gold is None:
            continue
        text = " ".join(filter(None, [rec.get("title"), rec.get("description")]))
        pred = _predict_heuristic(text)
        total += 1
        if pred == gold:
            correct += 1
            per_class[gold]["tp"] += 1
        else:
            per_class[gold]["fn"] += 1
            if pred:
                per_class[pred]["fp"] += 1

    accuracy = correct / total if total else 0.0

    # Macro-F1
    f1_scores = []
    for cls, counts in per_class.items():
        tp = counts["tp"]
        fp = counts["fp"]
        fn = counts["fn"]
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec_score = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * prec * rec_score / (prec + rec_score) if (prec + rec_score) else 0.0
        f1_scores.append(f1)

    macro_f1 = sum(f1_scores) / len(f1_scores) if f1_scores else 0.0

    return {
        "task": "RB-1: Vulnerability Classification",
        "total_samples": total,
        "accuracy": round(accuracy, 4),
        "macro_f1": round(macro_f1, 4),
        "class_distribution": dict(Counter(rec.get("vuln_type") for rec in records if rec.get("vuln_type"))),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="RB-1: Vulnerability Classification benchmark")
    parser.add_argument("--split", default="test", choices=["train", "val", "test"])
    parser.add_argument("--dataset-dir", type=Path, default=Path("dataset"))
    args = parser.parse_args()

    findings_path = args.dataset_dir / args.split / "findings.jsonl"
    if not findings_path.exists():
        print(f"[ERROR] {findings_path} not found. Run generate_dataset.py first.", file=sys.stderr)
        sys.exit(1)

    records = read_jsonl(findings_path)
    results = evaluate(records)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
