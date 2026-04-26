"""
benchmarks/rb4_remediation_quality.py

RB-4: Remediation / Blue-Team Response Quality
===============================================
Task: Given a vulnerability description, generate remediation guidance.

Metric: ROUGE-L against reference remediation outputs in blue_team.jsonl.

Usage::

    python benchmarks/rb4_remediation_quality.py --split test --model-output /path/to/model_outputs.jsonl

``model_outputs.jsonl`` must have lines::

    {"finding_id": "...", "generated": "<model output text>"}
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent))

from utils import read_jsonl  # scripts/utils.py
from metrics import rouge_l   # benchmarks/metrics.py


def evaluate(
    blue_records: List[Dict[str, Any]],
    model_outputs: Dict[str, str],
) -> Dict[str, Any]:
    scores = []
    matched = 0
    for rec in blue_records:
        fid = rec.get("finding_id", "")
        reference = rec.get("output", "")
        generated = model_outputs.get(fid)
        if generated is None or not reference:
            continue
        score = rouge_l(reference, generated)
        scores.append(score)
        matched += 1

    avg_rouge_l = sum(scores) / len(scores) if scores else 0.0
    return {
        "task": "RB-4: Remediation Quality",
        "total_samples": len(blue_records),
        "matched_with_model_output": matched,
        "avg_rouge_l": round(avg_rouge_l, 4),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="RB-4: Remediation Quality benchmark")
    parser.add_argument("--split", default="test", choices=["train", "val", "test"])
    parser.add_argument("--dataset-dir", type=Path, default=Path("dataset"))
    parser.add_argument("--model-output", type=Path, default=None)
    args = parser.parse_args()

    blue_path = args.dataset_dir / args.split / "blue_team.jsonl"
    if not blue_path.exists():
        print(f"[ERROR] {blue_path} not found.", file=sys.stderr)
        sys.exit(1)

    blue_records = read_jsonl(blue_path)

    model_outputs: Dict[str, str] = {}
    if args.model_output and args.model_output.exists():
        for line in read_jsonl(args.model_output):
            if "finding_id" in line and "generated" in line:
                model_outputs[line["finding_id"]] = line["generated"]

    results = evaluate(blue_records, model_outputs)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
