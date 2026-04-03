# Pipeline Architecture

## Overview

The RedBlue pipeline ingests public penetration testing reports and produces
three structured JSONL datasets suitable for LLM training.

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
│   extract_text      │  PDF / HTML / MD / DOCX → plain text
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
│   heuristics        │  vuln_type / CWE / OWASP / severity / CVSS
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
| `extract_text.py` | Text extraction per file type (including OCR fallback) |
| `segment_report.py` | Structural segmentation of report text |
| `split_findings.py` | Finding extraction and structuring |
| `heuristics.py` | Vulnerability classification |
| `ollama_enhancer.py` | Optional LLM enrichment of findings |
| `process_reports.py` | Orchestration and dataset writing |

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

The workflow (`.github/workflows/build-dataset.yml`) runs on every push to
`main` and on manual `workflow_dispatch` with optional inputs.

### Steps

1. Checkout repository
2. Set up Python 3.11
3. Cache pip dependencies
4. Install `requirements.txt`
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
