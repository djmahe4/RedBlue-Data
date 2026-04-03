# Training Guide

This guide covers how to load the RedBlue dataset and use it to fine-tune
or evaluate language models.

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

Each record in `red_team.jsonl` and `blue_team.jsonl` already uses the
Alpaca instruction format:

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

```python
sqli_records = [r for r in red_data if r.get("vuln_type") == "SQLi"]
high_severity = [r for r in blue_data if r.get("severity") == "high"]
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
