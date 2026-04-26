---
license: cc-by-4.0
task_categories:
  - text-generation
  - text-classification
language:
  - en
tags:
  - cybersecurity
  - penetration-testing
  - red-team
  - blue-team
  - instruction-tuning
  - vulnerability
pretty_name: RedBlue-Data
size_categories:
  - 10K<n<100K
---

# RedBlue Dataset

A large-scale, production-ready cybersecurity instruction-tuning dataset derived from
real public penetration testing reports, optionally merged with external cybersecurity
datasets (SEvenLLM, CyberLLMInstruct, Trendyol, RedBench).

Designed for fine-tuning and evaluating LLMs on offensive (red-team) and defensive
(blue-team) cybersecurity tasks.

---

## Dataset Description

- **Homepage:** https://github.com/djmahe4/RedBlue-Data
- **Repository:** https://github.com/djmahe4/RedBlue-Data
- **License:** CC BY 4.0

### Summary

RedBlue-Data extracts structured vulnerability findings from the
[juliocesarfort/public-pentesting-reports](https://github.com/juliocesarfort/public-pentesting-reports)
corpus and converts them into instruction-tuning pairs for:

- **Red-team tasks:** exploit generation, attack scenario creation
- **Blue-team tasks:** remediation guidance, secure coding advice, defence strategies

---

## Dataset Structure

```
dataset/
├── raw/         # All findings before splitting
│   ├── findings.jsonl
│   ├── red_team.jsonl
│   └── blue_team.jsonl
├── train/       # 80 % of data (stratified)
│   ├── findings.jsonl
│   ├── red_team.jsonl
│   └── blue_team.jsonl
├── val/         # 10 %
└── test/        # 10 %
```

### Data Fields

#### `findings.jsonl`

| Field | Type | Description |
|-------|------|-------------|
| `report_id` | string | SHA-256-based report identifier |
| `finding_id` | string | Unique finding ID (`<report_id>_<index>`) |
| `vendor` | string | Reporting firm / external source name |
| `source_file` | string | Posix path to source file |
| `title` | string\|null | Vulnerability title |
| `description` | string\|null | Detailed description |
| `technical_details` | string\|null | PoC / technical details |
| `recommendation` | string\|null | Remediation guidance |
| `vuln_type` | string\|null | Vulnerability category (SQLi, XSS, RCE, …) |
| `cwe` | string\|null | CWE identifier (e.g. CWE-89) |
| `owasp` | string\|null | OWASP Top 10 category (e.g. A03:2021) |
| `severity` | string\|null | critical / high / medium / low / info |
| `cvss_score` | string\|null | CVSS numeric score |
| `source_dataset` | string\|null | External dataset name (if applicable) |
| `split` | string\|null | train / val / test |

#### `red_team.jsonl` / `blue_team.jsonl`

| Field | Type | Description |
|-------|------|-------------|
| `instruction` | string | Task instruction |
| `input` | string | Vulnerability context |
| `output` | string | Expected LLM output |
| `finding_id` | string | Back-reference to findings.jsonl |
| `vuln_type` | string\|null | Vulnerability category |
| `severity` | string\|null | Severity level |
| `split` | string\|null | train / val / test |

---

## Sample Records

### Finding

```json
{
  "report_id": "a1b2c3d4e5f6a1b2",
  "finding_id": "a1b2c3d4e5f6a1b2_0001",
  "vendor": "cure53",
  "source_file": "cure53/Foo-Audit-Report.pdf",
  "title": "SQL Injection in Login Form",
  "description": "The login endpoint accepts unsanitized user input directly in the SQL query.",
  "technical_details": "Payload: ' OR '1'='1",
  "recommendation": "Use parameterized queries or an ORM. Validate and sanitize all inputs.",
  "vuln_type": "SQLi",
  "cwe": "CWE-89",
  "owasp": "A03:2021",
  "severity": "high",
  "cvss_score": "8.1",
  "split": "train"
}
```

### Red-Team Pair

```json
{
  "instruction": "Generate a detailed exploit or attack scenario for the following vulnerability.",
  "input": "Title: SQL Injection in Login Form\nDescription: The login endpoint accepts unsanitized user input...",
  "output": "Payload: ' OR '1'='1 -- bypasses authentication...",
  "finding_id": "a1b2c3d4e5f6a1b2_0001",
  "vuln_type": "SQLi",
  "severity": "high",
  "split": "train"
}
```

### Blue-Team Pair

```json
{
  "instruction": "Provide a secure fix and remediation guidance for the following vulnerability.",
  "input": "Title: SQL Injection in Login Form\nDescription: ...",
  "output": "Use parameterized queries or an ORM. Validate and sanitize all inputs.",
  "finding_id": "a1b2c3d4e5f6a1b2_0001",
  "vuln_type": "SQLi",
  "severity": "high",
  "split": "train"
}
```

---

## Usage

### Load with 🤗 Datasets

```python
from datasets import load_dataset

# Load a specific split
train = load_dataset("json", data_files="dataset/train/red_team.jsonl", split="train")
test  = load_dataset("json", data_files="dataset/test/blue_team.jsonl",  split="train")
```

### Fine-tune with TRL SFTTrainer

```python
from datasets import load_dataset
from trl import SFTTrainer, SFTConfig
from transformers import AutoModelForCausalLM, AutoTokenizer

model = AutoModelForCausalLM.from_pretrained("meta-llama/Llama-3.2-3B")
tokenizer = AutoTokenizer.from_pretrained("meta-llama/Llama-3.2-3B")

train_dataset = load_dataset(
    "json",
    data_files="dataset/train/red_team.jsonl",
    split="train",
)

def format_prompt(example):
    return f"### Instruction:\n{example['instruction']}\n\n### Input:\n{example['input']}\n\n### Response:\n{example['output']}"

trainer = SFTTrainer(
    model=model,
    train_dataset=train_dataset,
    formatting_func=format_prompt,
    args=SFTConfig(output_dir="./redblue-finetuned", num_train_epochs=3),
)
trainer.train()
```

---

## Benchmark Tasks

| ID | Task | Metric |
|----|------|--------|
| RB-1 | Vulnerability Classification | Accuracy, Macro-F1 |
| RB-2 | Severity Prediction | Accuracy, Weighted-F1 |
| RB-3 | Exploit / Attack Generation | ROUGE-L |
| RB-4 | Remediation Quality | ROUGE-L |
| RB-5 | Dataset Statistics & Coverage | Coverage metrics |

Run all benchmarks:

```bash
python benchmarks/rb1_vuln_classification.py --split test
python benchmarks/rb2_severity_prediction.py --split test
python benchmarks/rb5_dataset_stats.py --all-splits
```

---

## Regenerating the Dataset

```bash
# Basic
python scripts/generate_dataset.py --max-reports 100

# With external datasets + Ollama enrichment
python scripts/generate_dataset.py --merge-external --use-ollama --ollama-model llama3.2

# Full run with custom splits + push to Hub
python scripts/generate_dataset.py \
    --split-ratios 0.8 0.1 0.1 \
    --push-to-hub myuser/redblue-data
```

---

## External Datasets (Optional Merge)

When `--merge-external` is used, the pipeline scans `external_datasets/` for JSONL/JSON
files, maps them to the unified schema (optionally via Ollama semantic mapping), deduplicates
against internal records using TF-IDF cosine similarity, and merges them into all splits.

Recommended complementary datasets:

| Dataset | Size | Focus |
|---------|------|-------|
| [SEvenLLM-Instruct](https://huggingface.co/Multilingual-Multimodal-NLP/SEVENLLM-Dataset) | 91k+ pairs | CTI, 27 blue-team tasks |
| [CyberLLMInstruct](https://github.com/adelsamir01/CyberLLMInstruct) | 55k pairs | Offensive diversity |
| [Trendyol Cybersecurity](https://huggingface.co/Trendyol/Trendyol-Cybersecurity-Instruction-Tuning-Dataset) | 53k+ pairs | General cyber coverage |
| [RedBench](https://huggingface.co/knoveleng/redbench) | ~29k pairs | Red-team samples |

---

## Source Attribution

All internal findings are derived from publicly available penetration testing reports at:
**<https://github.com/juliocesarfort/public-pentesting-reports>**

Original reports are the property of their respective authors and firms.
This dataset is provided for research and educational purposes only.

---

## Privacy

All records have been automatically de-identified:
- IP addresses → `[IP_REDACTED]`
- Email addresses → `[EMAIL_REDACTED]`
- Credentials/tokens → `[REDACTED]`

---

## Citation

```bibtex
@misc{redblue-data,
  title  = {RedBlue-Data: A Cybersecurity Instruction-Tuning Dataset},
  author = {djmahe4},
  year   = {2024},
  url    = {https://github.com/djmahe4/RedBlue-Data},
}
```
