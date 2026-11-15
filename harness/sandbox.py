"""Restricted Python execution boundary for the harness."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


def run_code(code: str, *, approved: bool = False, workspace: Path | None = None) -> dict:
    """Run code in the sandbox image, with network disabled by default."""
    if not approved:
        raise PermissionError("Code execution requires no HITL approval")
    root = (workspace or Path.cwd()).resolve()
    command = [
        "docker", "run", "--rm", "--network=none",
        "--read-only", "-v", f"{root}:/workspace:ro",
        os.environ.get("REDBLUE_SANDBOX_IMAGE", "redblue-sandbox"),
        code,
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
    return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
