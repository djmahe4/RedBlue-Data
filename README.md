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

# Run the pipeline
python scripts/process_reports.py --max_reports 30

# Run tests
pytest tests/
```

## Documentation

- [Dataset Usage](docs/DATASET_USAGE.md)
- [Training Guide](docs/TRAINING_GUIDE.md)
- [Pipeline Architecture](docs/PIPELINE_ARCHITECTURE.md)
- [Dataset README](dataset/README.md)
