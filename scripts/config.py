"""
config.py - Configuration system with CLI > ENV > defaults priority.
"""
from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, field
from typing import List


@dataclass
class Config:
    max_reports: int
    max_file_size_mb: float
    allowed_extensions: List[str]
    output_dir: str
    source_repo: str
    incremental: bool
    full_run: bool

    def print_config(self) -> None:
        print("=== Pipeline Configuration ===")
        print(f"  max_reports       : {self.max_reports}")
        print(f"  max_file_size_mb  : {self.max_file_size_mb}")
        print(f"  allowed_extensions: {self.allowed_extensions}")
        print(f"  output_dir        : {self.output_dir}")
        print(f"  source_repo       : {self.source_repo}")
        print(f"  incremental       : {self.incremental}")
        print(f"  full_run          : {self.full_run}")
        print("==============================")

    def as_dict(self) -> dict:
        return {
            "max_reports": self.max_reports,
            "max_file_size_mb": self.max_file_size_mb,
            "allowed_extensions": self.allowed_extensions,
            "output_dir": self.output_dir,
            "source_repo": self.source_repo,
            "incremental": self.incremental,
            "full_run": self.full_run,
        }


def _parse_bool(value: str) -> bool:
    return value.lower() in ("1", "true", "yes", "on")


def _parse_extensions(value: str) -> List[str]:
    return [ext.strip().lstrip(".").lower() for ext in value.split(",") if ext.strip()]


def get_config(argv: list | None = None) -> Config:
    """
    Build Config with priority: CLI args > ENV vars > defaults.
    """
    parser = argparse.ArgumentParser(
        description="RedBlue cybersecurity dataset pipeline",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--max_reports",
        type=int,
        default=None,
        help="Maximum number of reports to process (env: MAX_REPORTS)",
    )
    parser.add_argument(
        "--max_file_size_mb",
        type=float,
        default=None,
        help="Maximum file size in MB to process (env: MAX_FILE_SIZE_MB)",
    )
    parser.add_argument(
        "--allowed_extensions",
        type=str,
        default=None,
        help="Comma-separated list of allowed extensions (env: ALLOWED_EXTENSIONS)",
    )
    parser.add_argument(
        "--output_dir",
        type=str,
        default=None,
        help="Output directory for dataset files (env: OUTPUT_DIR)",
    )
    parser.add_argument(
        "--source_repo",
        type=str,
        default=None,
        help="URL of the pentest reports source repo (env: SOURCE_REPO)",
    )
    parser.add_argument(
        "--no_incremental",
        action="store_true",
        default=False,
        help="Disable incremental processing (env: INCREMENTAL=false)",
    )
    parser.add_argument(
        "--full_run",
        action="store_true",
        default=False,
        help="Process all reports ignoring max_reports limit",
    )

    args = parser.parse_args(argv)

    # Resolve each parameter: CLI > ENV > default
    max_reports: int
    if args.max_reports is not None:
        max_reports = args.max_reports
    elif os.environ.get("MAX_REPORTS"):
        max_reports = int(os.environ["MAX_REPORTS"])
    else:
        max_reports = 30

    max_file_size_mb: float
    if args.max_file_size_mb is not None:
        max_file_size_mb = args.max_file_size_mb
    elif os.environ.get("MAX_FILE_SIZE_MB"):
        max_file_size_mb = float(os.environ["MAX_FILE_SIZE_MB"])
    else:
        max_file_size_mb = 5.0

    allowed_extensions: List[str]
    if args.allowed_extensions is not None:
        allowed_extensions = _parse_extensions(args.allowed_extensions)
    elif os.environ.get("ALLOWED_EXTENSIONS"):
        allowed_extensions = _parse_extensions(os.environ["ALLOWED_EXTENSIONS"])
    else:
        allowed_extensions = ["pdf", "md", "html", "docx"]

    output_dir: str
    if args.output_dir is not None:
        output_dir = args.output_dir
    elif os.environ.get("OUTPUT_DIR"):
        output_dir = os.environ["OUTPUT_DIR"]
    else:
        output_dir = "dataset"

    source_repo: str
    if args.source_repo is not None:
        source_repo = args.source_repo
    elif os.environ.get("SOURCE_REPO"):
        source_repo = os.environ["SOURCE_REPO"]
    else:
        source_repo = "https://github.com/juliocesarfort/public-pentesting-reports"

    incremental: bool
    if args.no_incremental:
        incremental = False
    elif os.environ.get("INCREMENTAL"):
        incremental = _parse_bool(os.environ["INCREMENTAL"])
    else:
        incremental = True

    full_run: bool = args.full_run or _parse_bool(os.environ.get("FULL_RUN", "false"))

    return Config(
        max_reports=max_reports,
        max_file_size_mb=max_file_size_mb,
        allowed_extensions=allowed_extensions,
        output_dir=output_dir,
        source_repo=source_repo,
        incremental=incremental,
        full_run=full_run,
    )
