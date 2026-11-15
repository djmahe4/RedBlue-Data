# Training Guide

This guide covers how to load the RedBlue dataset and use it to fine-tune
or evaluate language models.

## Label provenance and review

`vuln_type`, `cwe`, and `owasp` come from deterministic phrase rules over the
report title and description. `classification_status: rule_matched` means a
configured phrase matched; it does **not** verify that the report's finding is
correct. `classification_evidence` stores the matched source phrase.

No match leaves canonical classification fields empty and sets
`classification_status: unclassified`. If optional Ollama processing is enabled,
it may attach `ai_classification_suggestion` only when it can cite an exact quote
from the source title/description. The suggestion remains `unverified`; it never
fills the canonical labels. Validate against the original report before using
any rule label or AI suggestion as ground truth.

Syscall events shown by the harness dashboard are runtime telemetry, not report
content, and are not used as classification evidence or training labels. The
current repository has a syscall receiver but no Rust collector.

---

## Loading the Dataset

### With the `datasets` library (Hugging Face)

```python
from datasets import load_dataset

# Load red-team split
red = load_dataset("json", data_files="dataset/red_team.jsonl", split="train")

# Load blue-team split
blue = load_dataset("json", data_files="dataset/blue_team.jsonl", split="train")

print(red[0])
```

### With plain Python

```python
import json
from pathlib import Path

def load_jsonl(path):
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]

red_data = load_jsonl("dataset/red_team.jsonl")
blue_data = load_jsonl("dataset/blue_team.jsonl")
```

---

## Fine-tuning Example (Alpaca-style format)

Each record in `red_team.jsonl` and `blue_team.jsonl` uses the Alpaca
instruction format. The `output` is copied from report technical details or
recommendations; it is not an independently validated model answer. Review
source licensing, safety, and label provenance before training:

```json
{
  "instruction": "Generate a detailed exploit or attack scenario for the following vulnerability.",
  "input": "Title: SQL Injection\nDescription: The login form is vulnerable ...",
  "output": "An attacker could craft the following payload ..."
}
```

### Using `transformers` + `trl`

```python
from datasets import load_dataset
from transformers import AutoTokenizer, AutoModelForCausalLM
from trl import SFTTrainer, SFTConfig

def format_record(record):
    return (
        f"### Instruction:\n{record['instruction']}\n\n"
        f"### Input:\n{record['input']}\n\n"
        f"### Response:\n{record['output']}"
    )

dataset = load_dataset("json", data_files="dataset/red_team.jsonl", split="train")
dataset = dataset.map(lambda x: {"text": format_record(x)})

model_name = "meta-llama/Llama-3.2-1B"
tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForCausalLM.from_pretrained(model_name)

trainer = SFTTrainer(
    model=model,
    train_dataset=dataset,
    args=SFTConfig(output_dir="./output", max_seq_length=1024),
)
trainer.train()
```

---

## Dataset Statistics

Run `python scripts/process_reports.py` to regenerate the dataset.
Check `dataset/stats.json` for counts of processed reports and findings.

---

## Filtering by Vulnerability Type

Both training splits carry `classification_status`, `classification_evidence`,
and optional `ai_classification_suggestion`. Filtered records are still not
verified ground truth; use a separately reviewed allowlist when training against
confirmed labels:

```python
reviewed_finding_ids = set()  # Populate from a human-reviewed manifest.
reviewed_red = [
    record for record in red_data
    if record.get("finding_id") in reviewed_finding_ids
]
```

To inspect rule matches without treating them as confirmed:

```python
rule_matches = [r for r in red_data if r.get("classification_status") == "rule_matched"]
unclassified = [r for r in red_data if r.get("classification_status") == "unclassified"]
needs_ai_review = [
    r for r in unclassified if r.get("ai_classification_suggestion", {}).get("status") == "unverified"
]
```

---

## Filtering by OWASP Category

```python
a03_records = [r for r in red_data if r.get("owasp") == "A03:2021"]
```

---

## Notes

- All records have been privacy-masked (IPs, emails, credentials).
- `output` fields may be empty for findings without technical details or recommendations.
- Cross-reference `finding_id` between the three dataset files for full context.
