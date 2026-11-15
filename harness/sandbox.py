"""Restricted execution boundary for the harness."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

# Define a safe parent directory where all allowed workspaces live
ALLOWED_WORKSPACES_ROOT = Path(
    os.environ.get("REDBLUE_WORKSPACES_ROOT", "/var/app/workspaces")
).resolve()
ALLOWED_WORKSPACES_ROOT.mkdir(parents=True, exist_ok=True)



def run_sandbox(code: str, workspace: Path | str | None = None, approved: bool = False):
    """Run code or shell commands in the sandbox image, with network disabled by default."""
    if not approved:
        raise PermissionError("Sandbox execution requires HITL approval")

    # Resolve the requested workspace (or default to the safe base directory)
    root = Path(workspace).resolve() if workspace else ALLOWED_WORKSPACES_ROOT

    # Ensure the resolved path is inside the allowed directory and exists
    if not root.is_relative_to(ALLOWED_WORKSPACES_ROOT):
        raise ValueError(f"Workspace path '{root}' escapes allowed base '{ALLOWED_WORKSPACES_ROOT}'")

    if not root.is_dir():
        raise FileNotFoundError(f"Workspace directory does not exist: '{root}'")

    # Safe to mount `root` into Docker now
    command = [
        "docker", "run", "--rm", "--network=none",
        "--read-only",
        "--tmpfs", "/tmp:rw,nosuid,size=512m",
        "-e", "HOME=/tmp",
        "-e", "GOCACHE=/tmp/go-cache",
        "-e", "CARGO_TARGET_DIR=/tmp/cargo-target",
        "-v", f"{root}:/workspace:ro",
        os.environ.get("REDBLUE_SANDBOX_IMAGE", "redblue-sandbox"),
        "/bin/sh", "-c", code,
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
    return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
