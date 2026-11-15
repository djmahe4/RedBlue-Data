"""Nemotron document parsing adapter with content-addressed caching.

The adapter intentionally speaks a small HTTP JSON contract so the local
Nemotron service can be replaced without changing the dataset pipeline:

    POST $NEMOTRON_OCR_URL
    multipart field ``image`` containing the source image
    response JSON containing ``markdown``, ``bboxes``, ``classes`` and
    ``confidence``.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any
from urllib import error, request

try:
    from langchain_core.tools import tool
except ImportError:  # Keep the adapter usable with the repository's base requirements.
    def tool(func):  # type: ignore[no-untyped-def]
        return func


_REQUIRED_KEYS = ("markdown", "bboxes", "classes", "confidence")
_DEFAULT_CACHE_DIR = Path("dataset/cache/ocr")


def _cache_path(image_path: Path, cache_dir: Path) -> Path:
    digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
    return cache_dir / f"{digest}.json"


def _normalise(payload: dict[str, Any]) -> dict[str, Any]:
    missing = [key for key in _REQUIRED_KEYS if key not in payload]
    if missing:
        raise ValueError(f"Nemotron response missing required fields: {', '.join(missing)}")
    return {
        "markdown": str(payload["markdown"]),
        "bboxes": payload["bboxes"],
        "classes": payload["classes"],
        "confidence": payload["confidence"],
    }


def _multipart_body(image_path: Path) -> tuple[bytes, str]:
    boundary = "redblue-nemotron-boundary"
    content = image_path.read_bytes()
    filename = image_path.name.replace('"', "")
    header = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode()
    return header + content + f"\r\n--{boundary}--\r\n".encode(), boundary


@tool
def ocr_document(image_path: str | Path) -> dict[str, Any]:
    """Parse an image with local Nemotron Parse 2.0 and cache the result."""
    path = Path(image_path)
    if not path.is_file():
        raise FileNotFoundError(f"OCR image does not exist: {path}")

    cache_dir = Path(os.environ.get("NEMOTRON_OCR_CACHE_DIR", _DEFAULT_CACHE_DIR))
    cache_file = _cache_path(path, cache_dir)
    if cache_file.is_file():
        try:
            return _normalise(json.loads(cache_file.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, ValueError):
            cache_file.unlink(missing_ok=True)

    endpoint = os.environ.get("NEMOTRON_OCR_URL")
    if not endpoint:
        raise RuntimeError(
            "NEMOTRON_OCR_URL is not configured; start the local Nemotron service "
            "or use the existing Tesseract fallback."
        )

    body, boundary = _multipart_body(path)
    req = request.Request(
        endpoint,
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=float(os.environ.get("NEMOTRON_OCR_TIMEOUT", "120"))) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Nemotron OCR request failed for {path}: {exc}") from exc

    result = _normalise(payload)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result
