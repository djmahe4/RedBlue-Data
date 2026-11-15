"""Run the existing dataset pipeline in the configured user workspace."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def generate_dataset(options: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run process_reports.py locally; never dispatch dataset generation to Docker."""
    if options is None:
        options = {}
    if not isinstance(options, dict):
        raise ValueError("dataset_options must be an object")
    workspace = Path(os.environ.get("REDBLUE_WORKSPACE", PROJECT_ROOT)).resolve()
    if not workspace.is_dir():
        raise FileNotFoundError(f"Workspace directory does not exist: '{workspace}'")

    command = [sys.executable, str(PROJECT_ROOT / "scripts" / "process_reports.py")]
    for option, flag, value_type in (
        ("max_reports", "--max_reports", int),
        ("max_file_size_mb", "--max_file_size_mb", float),
    ):
        if option in options:
            value = options[option]
            if isinstance(value, bool) or not isinstance(value, (int, float, str)):
                raise ValueError(f"{option} must be a number")
            parsed = value_type(value)
            if parsed <= 0:
                raise ValueError(f"{option} must be greater than zero")
            command.extend((flag, str(parsed)))

    output_dir = options.get("output_dir")
    if output_dir is not None:
        output_path = (workspace / str(output_dir)).resolve()
        if not output_path.is_relative_to(workspace):
            raise ValueError("output_dir must stay inside the configured workspace")
        command.extend(("--output_dir", str(output_path)))

    for option, flag in (("skip_ocr", "--skip_ocr"), ("full_run", "--full_run")):
        if option in options and not isinstance(options[option], bool):
            raise ValueError(f"{option} must be a boolean")
        if options.get(option, False):
            command.append(flag)

    env = os.environ.copy()
    if "skip_ocr" in options:
        env["SKIP_OCR"] = "true" if options["skip_ocr"] else "false"

    result = subprocess.run(
        command,
        cwd=workspace,
        env=env,
        capture_output=True,
        text=True,
        timeout=3600,
        check=False,
    )
    return {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "workspace": str(workspace),
    }
