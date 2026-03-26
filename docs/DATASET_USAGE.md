# Dataset Usage Guide

## Overview

The RedBlue dataset is a structured collection of cybersecurity findings extracted from
public penetration testing reports. It is designed to train and evaluate large language
models (LLMs) on offensive security reasoning (red team) and defensive remediation
(blue team) tasks.

---

## Files

| File | Description |
|------|-------------|
| `findings.jsonl` | Full structured finding records |
| `red_team.jsonl` | Instruction–input–output tuples for exploit generation |
| `blue_team.jsonl` | Instruction–input–output tuples for secure fix generation |
| `manifest.json` | Pipeline run metadata |
| `stats.json` | High-level statistics for the last run |

---

## Schema

### `findings.jsonl`

Each line is a JSON object with the following fields:

| Field | Type | Description |
|-------|------|-------------|
| `report_id` | string | SHA-256-derived 16-char identifier for the source report |
| `finding_id` | string | `<report_id>_<index>` |
| `vendor` | string | Pentest firm name (top-level folder in source repo) |
| `source_file` | string | Original file path (relative to `reports-source/`) |
| `file_type` | string | `pdf`, `md`, `html`, or `docx` |
| `file_size_mb` | float | File size in megabytes |
| `exec_summary` | string\|null | Extracted executive summary section |
| `title` | string\|null | Finding title |
| `description` | string\|null | Short description |
| `technical_details` | string\|null | Technical details / PoC |
| `recommendation` | string\|null | Remediation guidance |
| `vuln_type` | string\|null | e.g. `SQLi`, `XSS`, `RCE` |
| `cwe` | string\|null | e.g. `CWE-89` |
| `owasp` | string\|null | e.g. `A03:2021` |
| `severity` | string\|null | `critical`, `high`, `medium`, `low`, `info` |
| `cvss_score` | string\|null | Numeric CVSS score (if present) |

### `red_team.jsonl`

| Field | Type | Description |
|-------|------|-------------|
| `instruction` | string | Task instruction for the LLM |
| `input` | string | Title + description of the finding |
| `output` | string | Technical details / exploit scenario |
| `finding_id` | string | Cross-reference to `findings.jsonl` |
| `vuln_type` | string\|null | Vulnerability type |
| `severity` | string\|null | Severity level |

### `blue_team.jsonl`

| Field | Type | Description |
|-------|------|-------------|
| `instruction` | string | Task instruction for the LLM |
| `input` | string | Title + description of the finding |
| `output` | string | Remediation guidance |
| `finding_id` | string | Cross-reference to `findings.jsonl` |
| `vuln_type` | string\|null | Vulnerability type |
| `severity` | string\|null | Severity level |

---

## Red vs Blue Usage

### Red Team (Offensive)

Use `red_team.jsonl` to train models that:
- Understand how vulnerabilities can be exploited
- Generate attack narratives or PoC scenarios
- Support automated red-team exercises

### Blue Team (Defensive)

Use `blue_team.jsonl` to train models that:
- Recommend secure coding practices
- Generate remediation plans
- Support security code review assistants

---

## Privacy

All sensitive data has been automatically redacted before dataset generation:
- IP addresses → `[IP_REDACTED]`
- Email addresses → `[EMAIL_REDACTED]`
- Credentials/tokens → `[REDACTED]`

---

## Source Attribution

Data extracted from: <https://github.com/juliocesarfort/public-pentesting-reports>

License of the original reports varies per vendor. This dataset is provided for
research and educational purposes only.
