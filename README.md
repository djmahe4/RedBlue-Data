# RedBlue-Data

A production-ready cybersecurity dataset pipeline that extracts structured
findings from public penetration testing reports and generates instruction-tuning
datasets for red-team (offensive) and blue-team (defensive) LLM training.

## Quick Start

```bash
# Clone this repo
git clone https://github.com/djmahe4/RedBlue-Data
cd RedBlue-Data

# Create and activate a virtual environment with uv
uv venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
uv pip install -r requirements.txt

# Create local configuration; edit .env for your setup
# Windows: copy .env.example .env
# macOS/Linux: cp .env.example .env

# Clone the pentest reports source into the configured workspace
git clone --depth 1 https://github.com/juliocesarfort/public-pentesting-reports reports-source

# Start the application entrypoint: agentic FastAPI harness
uvicorn api.main:app --reload
```

The harness can use local Ollama to select one allowlisted tool when
`HARNESS_PLANNER=ollama`; deterministic keyword routing remains the default.
Tool arguments come from the request, and external or dataset actions still
require approval. Dataset runs call `scripts/process_reports.py` through
`harness/dataset_runner.py`. That script is also a standalone batch entrypoint:

```bash
python scripts/process_reports.py --max_reports 30
python scripts/process_reports.py --use_ollama --ollama_model llama3
pytest tests/ -q
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

## Documentation

- [Dataset Usage](docs/DATASET_USAGE.md)
- [Training Guide](docs/TRAINING_GUIDE.md)
- [Pipeline Architecture](docs/PIPELINE_ARCHITECTURE.md)
- [Harness Operations](docs/HARNESS_OPERATIONS.md)
- [Dataset README](dataset/README.md)
