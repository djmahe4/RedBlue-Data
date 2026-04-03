"""
benchmarks/rb2_severity_prediction.py

RB-2: Severity Prediction
==========================
Task: Given a finding description, predict severity (critical/high/medium/low/info).

Metric: Accuracy and weighted-F1 over severity labels.

Usage::

    python benchmarks/rb2_severity_prediction.py --split test
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
    return classify_finding(text)["severity"]


def evaluate(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    correct = 0
    total = 0
    per_class: Dict[str, Dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0, "support": 0})

    for rec in records:
        gold = rec.get("severity")
        if gold is None:
            continue
        text = " ".join(filter(None, [rec.get("title"), rec.get("description")]))
        pred = _predict_heuristic(text)
        total += 1
        per_class[gold]["support"] += 1
        if pred == gold:
            correct += 1
            per_class[gold]["tp"] += 1
        else:
            per_class[gold]["fn"] += 1
            if pred:
                per_class[pred]["fp"] += 1

    accuracy = correct / total if total else 0.0
    total_support = sum(v["support"] for v in per_class.values())

    # Weighted-F1
    f1_weighted_sum = 0.0
    for cls, counts in per_class.items():
        tp = counts["tp"]
        fp = counts["fp"]
        fn = counts["fn"]
        support = counts["support"]
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec_score = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * prec * rec_score / (prec + rec_score) if (prec + rec_score) else 0.0
        f1_weighted_sum += f1 * support

    weighted_f1 = f1_weighted_sum / total_support if total_support else 0.0

    return {
        "task": "RB-2: Severity Prediction",
        "total_samples": total,
        "accuracy": round(accuracy, 4),
        "weighted_f1": round(weighted_f1, 4),
        "severity_distribution": dict(Counter(rec.get("severity") for rec in records if rec.get("severity"))),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="RB-2: Severity Prediction benchmark")
    parser.add_argument("--split", default="test", choices=["train", "val", "test"])
    parser.add_argument("--dataset-dir", type=Path, default=Path("dataset"))
    args = parser.parse_args()

    findings_path = args.dataset_dir / args.split / "findings.jsonl"
    if not findings_path.exists():
        print(f"[ERROR] {findings_path} not found.", file=sys.stderr)
        sys.exit(1)

    records = read_jsonl(findings_path)
    results = evaluate(records)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
