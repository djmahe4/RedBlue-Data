"""
merge_external.py - Merge external cybersecurity datasets into the RedBlue schema.

Scans ``external_datasets/`` for JSONL/JSON files and maps records to the
unified Finding / RedTeamPair / BlueTeamPair schema.

Optional LLM-driven semantic mapping via Ollama; falls back to rule-based
heuristics when Ollama is disabled or unavailable.

Deduplication uses TF-IDF cosine similarity to detect near-duplicate records
across internal and external sources.

Usage (standalone)::

    python scripts/merge_external.py \\
        --external-dir external_datasets \\
        --output-dir dataset/raw \\
        --use-ollama --ollama-model llama3.2

Or import and call ``merge_external_datasets()`` from generate_dataset.py.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).parent))

from heuristics import classify_finding
from schemas import Finding, RedTeamPair, BlueTeamPair
from utils import JSONLWriter, read_jsonl

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# TF-IDF deduplication
# ---------------------------------------------------------------------------

def _build_dedup_corpus(records: List[Dict[str, Any]]) -> List[str]:
    """Build a text corpus for TF-IDF from a list of records."""
    texts = []
    for r in records:
        parts = [
            r.get("title") or "",
            r.get("description") or "",
            r.get("input") or "",
            r.get("output") or "",
        ]
        texts.append(" ".join(p for p in parts if p).strip())
    return texts


def _deduplicate(
    new_records: List[Dict[str, Any]],
    existing_records: List[Dict[str, Any]],
    threshold: float = 0.92,
) -> List[Dict[str, Any]]:
    """
    Remove records from *new_records* that are near-duplicates of
    *existing_records* using TF-IDF cosine similarity.

    Parameters
    ----------
    new_records:
        Records to filter (external dataset records).
    existing_records:
        Already-accepted records to compare against.
    threshold:
        Cosine similarity threshold above which a record is considered duplicate.
    """
    if not existing_records or not new_records:
        return new_records

    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
        import numpy as np
    except ImportError:
        logger.warning("scikit-learn not available – skipping deduplication")
        return new_records

    existing_texts = _build_dedup_corpus(existing_records)
    new_texts = _build_dedup_corpus(new_records)

    # Fit vectorizer on combined corpus to share vocabulary
    all_texts = existing_texts + new_texts
    # Note: max_features=50_000 limits vocabulary size to control memory usage.
    # For very large external datasets (millions of records), consider reducing
    # this value or processing in batches.
    vectorizer = TfidfVectorizer(min_df=1, stop_words="english", max_features=50_000)
    try:
        tfidf_matrix = vectorizer.fit_transform(all_texts)
    except ValueError:
        return new_records

    existing_matrix = tfidf_matrix[: len(existing_texts)]
    new_matrix = tfidf_matrix[len(existing_texts):]

    unique: List[Dict[str, Any]] = []
    accepted_indices: List[int] = []

    for idx, new_vec in enumerate(new_matrix):
        # Compare against existing records
        sims_existing = cosine_similarity(new_vec, existing_matrix).flatten()
        if sims_existing.max() >= threshold:
            continue

        # Compare against already-accepted new records
        if accepted_indices:
            accepted_matrix = new_matrix[accepted_indices]
            sims_new = cosine_similarity(new_vec, accepted_matrix).flatten()
            if sims_new.max() >= threshold:
                continue

        unique.append(new_records[idx])
        accepted_indices.append(idx)

    logger.info(
        "Deduplication: %d/%d new records kept (removed %d duplicates)",
        len(unique),
        len(new_records),
        len(new_records) - len(unique),
    )
    return unique


# ---------------------------------------------------------------------------
# Heuristic field mapping
# ---------------------------------------------------------------------------

def _heuristic_map(record: Dict[str, Any]) -> Dict[str, Any]:
    """
    Map an arbitrary external record to RedBlue unified schema fields using
    simple heuristics.  Field names from common dataset formats are tried.
    """
    # Candidate text fields in priority order
    text_fields = [
        "instruction", "prompt", "question", "input", "context",
        "response", "answer", "output", "text", "content",
    ]

    combined_text = " ".join(
        str(record.get(f, "")) for f in text_fields if record.get(f)
    ).strip()

    classification = classify_finding(combined_text) if combined_text else {}

    # Try to find title
    title = (
        record.get("title")
        or record.get("finding")
        or record.get("vulnerability")
        or record.get("name")
        or None
    )

    # Try to find description
    description = (
        record.get("description")
        or record.get("context")
        or record.get("text")
        or record.get("content")
        or None
    )
    if description is None:
        # Compose from instruction / question + answer fields
        instruction = record.get("instruction") or record.get("question") or record.get("prompt") or ""
        response = record.get("response") or record.get("answer") or record.get("output") or ""
        if instruction:
            description = f"{instruction}\n{response}".strip() if response else instruction

    recommendation = (
        record.get("recommendation")
        or record.get("remediation")
        or record.get("mitigation")
        or record.get("fix")
        or None
    )

    return {
        "vuln_type": classification.get("vuln_type"),
        "cwe": classification.get("cwe"),
        "owasp": classification.get("owasp"),
        "severity": classification.get("severity"),
        "title": title,
        "description": description,
        "recommendation": recommendation,
        "red_suitable": True,
        "blue_suitable": recommendation is not None,
        "confidence": 5,
    }


# ---------------------------------------------------------------------------
# Record converter
# ---------------------------------------------------------------------------

def _to_finding(
    raw: Dict[str, Any],
    mapped: Dict[str, Any],
    source_name: str,
    idx: int,
) -> Optional[Finding]:
    """Construct a validated :class:`Finding` from raw + mapped fields."""
    finding_id = f"ext_{source_name}_{idx:06d}"
    try:
        return Finding(
            report_id=f"ext_{source_name}",
            finding_id=finding_id,
            source_file=f"external_datasets/{source_name}",
            vendor=source_name,
            title=mapped.get("title"),
            description=mapped.get("description"),
            recommendation=mapped.get("recommendation"),
            vuln_type=mapped.get("vuln_type"),
            cwe=mapped.get("cwe"),
            owasp=mapped.get("owasp"),
            severity=mapped.get("severity"),
            source_dataset=source_name,
        )
    except Exception as exc:
        logger.debug("Skipping malformed external record %s: %s", finding_id, exc)
        return None


def _to_pairs(
    finding: Finding,
    mapped: Dict[str, Any],
    raw: Dict[str, Any],
) -> Tuple[Optional[RedTeamPair], Optional[BlueTeamPair]]:
    """Build red/blue pairs from a validated finding and mapping metadata."""
    fid = finding.finding_id
    title = finding.title or ""
    description = finding.description or ""
    prompt_input = f"Title: {title}\nDescription: {description}".strip()

    red: Optional[RedTeamPair] = None
    blue: Optional[BlueTeamPair] = None

    # Prefer explicit attack/exploit text from the external record
    attack_text = (
        raw.get("attack")
        or raw.get("exploit")
        or raw.get("technical_details")
        or (raw.get("response") if not mapped.get("blue_suitable") else None)
        or description
    )

    if mapped.get("red_suitable") and prompt_input:
        try:
            red = RedTeamPair(
                instruction="Generate a detailed exploit or attack scenario for the following vulnerability.",
                input=prompt_input,
                output=attack_text or description,
                finding_id=fid,
                vuln_type=finding.vuln_type,
                severity=finding.severity,
                source_dataset=finding.source_dataset,
            )
        except Exception:
            pass

    if mapped.get("blue_suitable") and finding.recommendation and prompt_input:
        try:
            blue = BlueTeamPair(
                instruction="Provide a secure fix and remediation guidance for the following vulnerability.",
                input=prompt_input,
                output=finding.recommendation,
                finding_id=fid,
                vuln_type=finding.vuln_type,
                severity=finding.severity,
                source_dataset=finding.source_dataset,
            )
        except Exception:
            pass

    return red, blue


# ---------------------------------------------------------------------------
# File scanner
# ---------------------------------------------------------------------------

def _scan_external_dir(external_dir: Path) -> List[Tuple[str, Path]]:
    """
    Recursively find JSONL and JSON files in *external_dir*.
    Returns a list of (source_name, path) tuples.
    """
    results: List[Tuple[str, Path]] = []
    for p in sorted(external_dir.rglob("*")):
        if p.is_file() and p.suffix.lower() in (".jsonl", ".json"):
            # Use the first-level subdirectory as the source name
            try:
                rel = p.relative_to(external_dir)
                source_name = rel.parts[0] if len(rel.parts) > 1 else p.stem
            except ValueError:
                source_name = p.stem
            results.append((source_name, p))
    return results


def _load_file(path: Path) -> List[Dict[str, Any]]:
    """Load a JSON or JSONL file as a list of dicts."""
    records: List[Dict[str, Any]] = []
    try:
        if path.suffix.lower() == ".jsonl":
            records = read_jsonl(path)
        else:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, list):
                records = data
            elif isinstance(data, dict):
                # Some HF datasets are stored as {split: [records]}
                for v in data.values():
                    if isinstance(v, list):
                        records.extend(v)
    except Exception as exc:
        logger.warning("Failed to load %s: %s", path, exc)
    return records


# ---------------------------------------------------------------------------
# Main merge function
# ---------------------------------------------------------------------------

def merge_external_datasets(
    external_dir: Path,
    output_dir: Path,
    use_ollama: bool = False,
    ollama_model: str = "llama3.2",
    dedup_threshold: float = 0.92,
    existing_findings: Optional[List[Dict[str, Any]]] = None,
    max_per_source: Optional[int] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Scan *external_dir*, map records to unified schema, deduplicate, and
    return (findings, red_pairs, blue_pairs) ready for merging into the main
    dataset.

    Parameters
    ----------
    external_dir:
        Root directory containing external dataset subdirectories.
    output_dir:
        Where to write ``external_findings.jsonl``, ``external_red_team.jsonl``,
        and ``external_blue_team.jsonl``.
    use_ollama:
        Whether to call Ollama for semantic mapping of external records.
    ollama_model:
        Ollama model name.
    dedup_threshold:
        Cosine similarity threshold for deduplication (0-1).
    existing_findings:
        Already-processed findings to deduplicate against.
    max_per_source:
        Maximum records to load per source file (``None`` = no limit).

    Returns
    -------
    Tuple of (findings_dicts, red_dicts, blue_dicts).
    """
    if not external_dir.exists():
        logger.warning("external_datasets/ directory not found at %s", external_dir)
        return [], [], []

    source_files = _scan_external_dir(external_dir)
    if not source_files:
        logger.warning("No JSONL/JSON files found in %s", external_dir)
        return [], [], []

    logger.info("Found %d external files in %s", len(source_files), external_dir)

    ollama_map_fn = None
    if use_ollama:
        try:
            from ollama_enhancer import check_ollama_available, map_external_record
            if check_ollama_available(ollama_model):
                ollama_map_fn = lambda rec: map_external_record(rec, model=ollama_model)
                logger.info("Ollama semantic mapping enabled (model: %s)", ollama_model)
            else:
                logger.warning("Ollama not available – using heuristic mapping only")
        except ImportError:
            logger.warning("ollama_enhancer not importable – using heuristic mapping only")

    all_findings: List[Dict[str, Any]] = list(existing_findings or [])
    new_findings: List[Dict[str, Any]] = []
    new_red: List[Dict[str, Any]] = []
    new_blue: List[Dict[str, Any]] = []

    for source_name, fpath in source_files:
        logger.info("Processing external file: %s (%s)", fpath.name, source_name)
        raw_records = _load_file(fpath)
        if not raw_records:
            continue
        if max_per_source is not None:
            raw_records = raw_records[:max_per_source]

        batch_findings: List[Dict[str, Any]] = []
        batch_red: List[Dict[str, Any]] = []
        batch_blue: List[Dict[str, Any]] = []

        for idx, raw in enumerate(
            tqdm(raw_records, desc=f"Mapping {source_name}", leave=False)
        ):
            # Attempt LLM mapping first, fall back to heuristic
            mapped: Optional[Dict[str, Any]] = None
            if ollama_map_fn is not None:
                mapped = ollama_map_fn(raw)
            if mapped is None:
                mapped = _heuristic_map(raw)

            finding = _to_finding(raw, mapped, source_name, idx)
            if finding is None:
                continue

            red, blue = _to_pairs(finding, mapped, raw)
            batch_findings.append(finding.to_jsonl_dict())
            if red:
                batch_red.append(red.to_jsonl_dict())
            if blue:
                batch_blue.append(blue.to_jsonl_dict())

        # Deduplicate against all accepted findings so far
        deduped = _deduplicate(batch_findings, all_findings, threshold=dedup_threshold)
        deduped_ids = {r["finding_id"] for r in deduped}

        new_findings.extend(deduped)
        all_findings.extend(deduped)

        # Keep only red/blue pairs whose finding survived deduplication
        new_red.extend(r for r in batch_red if r["finding_id"] in deduped_ids)
        new_blue.extend(r for r in batch_blue if r["finding_id"] in deduped_ids)

    # Write outputs
    output_dir.mkdir(parents=True, exist_ok=True)
    with (
        JSONLWriter(output_dir / "external_findings.jsonl", mode="w") as fw,
        JSONLWriter(output_dir / "external_red_team.jsonl", mode="w") as rw,
        JSONLWriter(output_dir / "external_blue_team.jsonl", mode="w") as bw,
    ):
        for rec in new_findings:
            fw.write(rec)
        for rec in new_red:
            rw.write(rec)
        for rec in new_blue:
            bw.write(rec)

    logger.info(
        "External merge complete: %d findings, %d red-team, %d blue-team pairs",
        len(new_findings),
        len(new_red),
        len(new_blue),
    )
    return new_findings, new_red, new_blue


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _parse_args(argv: Optional[list] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Merge external cybersecurity datasets into the RedBlue schema",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--external-dir",
        type=Path,
        default=Path("external_datasets"),
        help="Root directory containing external dataset subdirectories",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("dataset/raw"),
        help="Output directory for merged JSONL files",
    )
    parser.add_argument(
        "--use-ollama",
        action="store_true",
        default=False,
        help="Enable Ollama semantic mapping",
    )
    parser.add_argument(
        "--ollama-model",
        type=str,
        default="llama3.2",
        help="Ollama model for semantic mapping",
    )
    parser.add_argument(
        "--dedup-threshold",
        type=float,
        default=0.92,
        help="TF-IDF cosine similarity threshold for deduplication",
    )
    parser.add_argument(
        "--max-per-source",
        type=int,
        default=None,
        help="Maximum records to load per source file",
    )
    return parser.parse_args(argv)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    args = _parse_args()
    merge_external_datasets(
        external_dir=args.external_dir,
        output_dir=args.output_dir,
        use_ollama=args.use_ollama,
        ollama_model=args.ollama_model,
        dedup_threshold=args.dedup_threshold,
        max_per_source=args.max_per_source,
    )


if __name__ == "__main__":
    main()
