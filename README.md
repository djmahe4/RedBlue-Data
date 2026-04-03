# RedBlue-Data

A production-ready cybersecurity dataset pipeline that extracts structured
findings from public penetration testing reports and generates instruction-tuning
datasets for red-team (offensive) and blue-team (defensive) LLM training.

## Quick Start

```bash
# Clone this repo
git clone https://github.com/djmahe4/RedBlue-Data

# Change path
cd RedBlue-Data

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

## Documentation

- [Dataset Usage](docs/DATASET_USAGE.md)
- [Training Guide](docs/TRAINING_GUIDE.md)
- [Pipeline Architecture](docs/PIPELINE_ARCHITECTURE.md)
- [Dataset README](dataset/README.md)
