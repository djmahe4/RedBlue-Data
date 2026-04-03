# RedBlue-Data

A production-ready cybersecurity dataset pipeline that extracts structured
findings from public penetration testing reports and generates instruction-tuning
datasets for red-team (offensive) and blue-team (defensive) LLM training.

## Quick Start

```bash
# 1. Setup RedBlue-Data
git clone https://github.com/djmahe4/RedBlue-Data.git
cd RedBlue-Data
git checkout copilot/build-cybersecurity-dataset-pipeline

# 2. Create folder for external data
mkdir -p external_datasets

# 3. Install HF CLI (one-time)
pip install huggingface_hub[hf_transfer]

# 4. Clone/Download the top complementary datasets (prioritized by report)
#    SEvenLLM-Instruct (91k+ high-quality CTI instruction pairs, 27 tasks) – BEST for blue-team + multi-task
huggingface-cli download Multilingual-Multimodal-NLP/SEVENLLM-Dataset --repo-type dataset --local-dir external_datasets/SEVENLLM

#    CyberLLMInstruct (55k pseudo-malicious red-team pairs) – excellent for offensive diversity
git clone https://github.com/adelsamir01/CyberLLMInstruct external_datasets/CyberLLMInstruct

#    Trendyol Cybersecurity Instruction-Tuning Dataset (53k+ pairs) – strong general cyber coverage
huggingface-cli download Trendyol/Trendyol-Cybersecurity-Instruction-Tuning-Dataset --repo-type dataset --local-dir external_datasets/Trendyol

#    (Optional but recommended for red-teaming)
huggingface-cli download knoveleng/redbench --repo-type dataset --local-dir external_datasets/RedBench   # ~29k red-team samples

# 5. Run your current pipeline once (generates base /dataset/ folder)
pip install -r requirements.txt
python scripts/process_reports.py --max_reports 100 --use_ollama   # or without Ollama first
```

## Full Dataset Generation

The `generate_dataset.py` script orchestrates the complete pipeline:
processes all reports, merges external datasets, runs Ollama enrichment,
and creates stratified train/val/test splits.

```bash
# Basic: process 100 reports, 80/10/10 split
python scripts/generate_dataset.py --max-reports 100

# With external merge + Ollama enrichment
python scripts/generate_dataset.py --merge-external --use-ollama --ollama-model llama3.2

# Full run with custom splits and push to Hugging Face Hub
python scripts/generate_dataset.py \
    --split-ratios 0.8 0.1 0.1 \
    --push-to-hub myuser/redblue-data
```

Output structure:

```
dataset/
├── raw/         findings.jsonl, red_team.jsonl, blue_team.jsonl
├── train/       findings.jsonl, red_team.jsonl, blue_team.jsonl
├── val/         findings.jsonl, red_team.jsonl, blue_team.jsonl
└── test/        findings.jsonl, red_team.jsonl, blue_team.jsonl
```

## Legacy Pipeline (process_reports.py)

```bash
# Clone the pentest reports source
git clone --depth 1 https://github.com/juliocesarfort/public-pentesting-reports reports-source

# Install dependencies
pip install -r requirements.txt

# Run the pipeline with basic options
python scripts/process_reports.py --max_reports 30

# Run with OCR enabled (if tesseract is installed) and Ollama enrichment
python scripts/process_reports.py --use_ollama --ollama_model llama3

# Run tests
pytest tests/
```

## Configuration

The pipeline supports several CLI options and environment variables:

| Option | Environment Variable | Default | Description |
|--------|----------------------|---------|-------------|
| `--max_reports` | `MAX_REPORTS` | `30` | Max reports to process |
| `--max_file_size_mb` | `MAX_FILE_SIZE_MB` | `5.0` | Max file size in MB |
| `--skip_ocr` | `SKIP_OCR` | `false` | Skip OCR for scanned PDFs |
| `--min_words` | `MIN_WORDS` | `20` | Min words to avoid OCR noise |
| `--use_ollama` | `OLLAMA_ENABLED` | `false` | Enable Ollama enrichment |
| `--ollama_model` | `OLLAMA_MODEL` | `llama3.2` | Ollama model to use |
| `--reset` | `RESET` | `false` | Wipe all existing files and manifest |

## Benchmark Tasks

Five evaluation tasks are provided in `benchmarks/`:

| ID | Task | Script |
|----|------|--------|
| RB-1 | Vulnerability Classification | `rb1_vuln_classification.py` |
| RB-2 | Severity Prediction | `rb2_severity_prediction.py` |
| RB-3 | Exploit Generation | `rb3_exploit_generation.py` |
| RB-4 | Remediation Quality | `rb4_remediation_quality.py` |
| RB-5 | Dataset Statistics | `rb5_dataset_stats.py` |

```bash
python benchmarks/rb1_vuln_classification.py --split test
python benchmarks/rb5_dataset_stats.py --all-splits
```

## Documentation

- [Dataset Usage](docs/DATASET_USAGE.md)
- [Training Guide](docs/TRAINING_GUIDE.md)
- [Pipeline Architecture](docs/PIPELINE_ARCHITECTURE.md)
- [Dataset README](dataset/README.md)
