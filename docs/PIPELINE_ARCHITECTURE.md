# Pipeline Architecture

## Overview

The RedBlue pipeline ingests public penetration testing reports and produces
three structured JSONL datasets suitable for LLM training.

The FastAPI harness can start and observe this pipeline from the user's
workspace. Dataset generation pauses for approval, then runs
`scripts/process_reports.py` locally in `REDBLUE_WORKSPACE` (default: project
root); it does not run dataset generation in the Docker sandbox.

```
POST /api/run/start -> planner -> HITL approval -> executor -> reflector
                                      |                 |
                               dataset pipeline    browser/search/OCR
```

`/dashboard/{run_id}` shows run status, graph events, pending approvals, and
syscall events. `/r3f/trace/{run_id}` provides trace nodes and edges. Browser
navigation/actions, web search, and dataset generation require approval.
Sandbox command execution is separate and requires `approved=True` at its
Python entry point.

The syscall endpoint is an ingestion API, not a collector. No Rust hook in this
repository calls it yet. A future collector must POST to
`/api/run/{run_id}/syscalls` with `X-Trace-Token` matching `REDBLUE_TRACE_TOKEN`.
Syscall telemetry is operational evidence only; it is not used to classify
report findings.

```
reports-source/           (cloned from juliocesarfort/public-pentesting-reports)
        │
        ▼
┌─────────────────────┐
│   process_reports   │  ← main orchestrator
│   (config + scan)   │
└────────┬────────────┘
         │ per-file
         ▼
┌─────────────────────┐
│   extract_text      │  PDF / HTML / MD / DOCX → text; scanned PDFs use configured OCR
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│   utils.mask_       │  Privacy masking (IPs, emails, credentials)
│   sensitive         │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│   segment_report    │  exec_summary / findings_raw / recommendations
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│   split_findings    │  Individual structured findings
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│   heuristics        │  rule match + exact evidence quote; otherwise unclassified
└────────┬────────────┘
         │
         ▼
┌─────────────────────────────────────────────┐
│  dataset/                                   │
│    findings.jsonl  (full records)           │
│    red_team.jsonl  (exploit instruction)    │
│    blue_team.jsonl (fix instruction)        │
│    manifest.json   (incremental state)      │
│    stats.json      (run statistics)         │
└─────────────────────────────────────────────┘
```

---

## Module Responsibilities

| Module | Responsibility |
|--------|----------------|
| `config.py` | CLI + ENV + defaults configuration system |
| `utils.py` | Hashing, file I/O, privacy masking, JSONL helpers |
| `extract_text.py` | Text extraction; scanned pages use configured OCR or Tesseract fallback |
| `tools/ocr.py` | Generic HTTP API or Ollama OCR, with Tesseract fallback |
| `tools/pdf_ocr.py` | PDF page rendering, image/vector region clustering, crop OCR, optional VLM notes |
| `segment_report.py` | Structural segmentation of report text |
| `split_findings.py` | Finding extraction and structuring |
| `heuristics.py` | Deterministic phrase matching; emits `rule_matched` plus the matching quote, or `unclassified` |
| `ollama_enhancer.py` | Optional, evidence-checked suggestions for unclassified findings; never changes canonical labels |
| `process_reports.py` | Orchestration and dataset writing |

### Classification provenance

A rule match means only that a configured phrase was found in the finding title
or description. It is not independent confirmation that the reported issue is
valid. The match and its exact quote are stored as `classification_status` and
`classification_evidence`. No match leaves canonical classification fields
empty and sets `classification_status` to `unclassified`.

When optional Ollama processing is enabled, only unclassified records are sent
for a candidate classification. The model must cite an exact substring from the
source title/description. Accepted candidates are stored separately as
`ai_classification_suggestion` with `status: unverified`; canonical `vuln_type`,
`cwe`, and `owasp` remain empty. The same provenance fields are copied into
`red_team.jsonl` and `blue_team.jsonl`. Review suggestions before treating them
as labels. Runtime syscall traces are not vulnerability evidence and are not
fed to this classifier.

`tools/ocr.py` accepts a generic configured HTTP endpoint (`OCR_PROVIDER=api`,
`OCR_API_URL`) or Ollama (`OCR_PROVIDER=ollama`); OpenAPI describes the HTTP
contract and is not a provider. See [Harness Operations](HARNESS_OPERATIONS.md)
and [the OCR API contract](ocr-api.openapi.yaml). `tools/pdf_ocr.py` adapts
page rendering, duplicate image-box removal, proximity clustering, crop
selection, and OCR to this pipeline. Optional VLM notes require an exact quote
from OCR text and remain unverified; they are not promoted into training labels.

---

## Configuration Priority

```
CLI args  >  ENV vars  >  Defaults
```

All thresholds are configurable:

| Parameter | CLI | ENV | Default |
|-----------|-----|-----|---------|
| max_reports | `--max_reports` | `MAX_REPORTS` | 30 |
| max_file_size_mb | `--max_file_size_mb` | `MAX_FILE_SIZE_MB` | 5.0 |
| allowed_extensions | `--allowed_extensions` | `ALLOWED_EXTENSIONS` | pdf,md,html,docx |
| output_dir | `--output_dir` | `OUTPUT_DIR` | dataset |
| source_repo | `--source_repo` | `SOURCE_REPO` | (juliocesarfort repo) |
| incremental | `--no_incremental` | `INCREMENTAL=false` | true |
| full_run | `--full_run` | `FULL_RUN=true` | false |
| skip_ocr | `--skip_ocr` | `SKIP_OCR` | false |
| min_words | `--min_words` | `MIN_WORDS` | 20 |
| use_ollama | `--use_ollama` | `OLLAMA_ENABLED` | false |
| ollama_model | `--ollama_model` | `OLLAMA_MODEL` | llama3 |
| reset | `--reset` | `RESET` | false |

---

## Incremental Processing

When `incremental=true` (default), the pipeline reads `manifest.json` to
skip already-processed reports. This makes re-runs fast and idempotent.

To force a full reprocess:

```bash
# Restart everything including wiping manifest.json
python scripts/process_reports.py --reset
```

---

## CI Execution (GitHub Actions)

The workflow (`.github/workflows/build-dataset.yml`) currently runs only on
manual `workflow_dispatch`; push triggers are commented out. OCR is enabled by
default in the workflow (`skip_ocr: false`).

### Steps

1. Checkout repository
2. Set up Python 3.11
3. Cache pip dependencies
4. Install Tesseract and `requirements.txt`
5. Clone source repository (shallow)
6. Run `python scripts/process_reports.py`
7. Run `pytest tests/`
8. Commit and push dataset if changed

### Workflow Inputs

| Input | Description |
|-------|-------------|
| `max_reports` | Maximum reports to process (default: 30) |
| `max_file_size_mb` | Max file size in MB (default: 5) |

---

## Local Execution

```bash
# 1. Clone the pentest reports source
git clone --depth 1 https://github.com/juliocesarfort/public-pentesting-reports reports-source

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run pipeline
python scripts/process_reports.py --max_reports 50

# 4. Run tests
pytest tests/
```

---

## Privacy & Security

All text passes through `utils.mask_sensitive()` before being written to disk:

- `[IP_REDACTED]` replaces IPv4 addresses
- `[EMAIL_REDACTED]` replaces email addresses
- `[REDACTED]` replaces credential-like patterns
