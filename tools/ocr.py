"""Provider-neutral OCR adapter with optional grounded VLM reasoning.

Set ``OCR_PROVIDER`` to ``api``, ``ollama``, or ``tesseract``. The generic API
backend POSTs to ``OCR_API_URL`` using the documented JSON payload; headers,
authentication, and extra body fields are configurable with environment
variables. OpenAPI describes that HTTP contract; it is not a model provider.
Ollama uses ``OLLAMA_BASE_URL`` and ``OCR_MODEL`` (or ``OLLAMA_OCR_MODEL``).
Auto mode selects configured API/Ollama settings, retains legacy
``NEMOTRON_OCR_URL`` support, then falls back to Tesseract.

Set ``VLM_MODEL`` to request an additional reasoning pass through the generic
API or Ollama. Output is retained only when it cites an exact quote from OCR
text, and remains marked unverified.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import mimetypes
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
logger = logging.getLogger(__name__)


def _parse_json_object(env_name: str) -> dict[str, Any]:
    raw = os.environ.get(env_name)
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{env_name} must contain a JSON object") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{env_name} must contain a JSON object")
    return value


def _parse_headers(env_name: str) -> dict[str, str]:
    headers = _parse_json_object(env_name)
    if any(not isinstance(key, str) or not isinstance(value, str) for key, value in headers.items()):
        raise ValueError(f"{env_name} keys and values must be strings")
    return headers


def _provider_config() -> dict[str, Any]:
    provider = os.environ.get("OCR_PROVIDER", "auto").strip().lower()
    if provider == "auto":
        if os.environ.get("OCR_API_URL"):
            provider = "api"
        elif os.environ.get("NEMOTRON_OCR_URL"):
            provider = "nemotron"
        elif os.environ.get("OLLAMA_OCR_MODEL") or (
            os.environ.get("OCR_MODEL") and os.environ.get("OLLAMA_BASE_URL")
        ):
            provider = "ollama"
        else:
            provider = "tesseract"

    if provider not in {"api", "ollama", "nemotron", "tesseract"}:
        raise ValueError("OCR_PROVIDER must be auto, api, ollama, or tesseract")

    model = os.environ.get("OCR_MODEL") or os.environ.get("OLLAMA_OCR_MODEL")
    if provider == "ollama" and not model:
        raise ValueError("OCR_MODEL or OLLAMA_OCR_MODEL is required for OCR_PROVIDER=ollama")
    if provider == "api" and not os.environ.get("OCR_API_URL"):
        raise ValueError("OCR_API_URL is required for OCR_PROVIDER=api")
    if provider == "nemotron" and not os.environ.get("NEMOTRON_OCR_URL"):
        raise ValueError("NEMOTRON_OCR_URL is required for the legacy provider")

    if provider == "api":
        endpoint = os.environ["OCR_API_URL"]
    elif provider == "ollama":
        base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
        endpoint = f"{base_url}/api/chat"
    elif provider == "nemotron":
        endpoint = os.environ["NEMOTRON_OCR_URL"]
    else:
        endpoint = ""

    return {
        "provider": provider,
        "model": model,
        "endpoint": endpoint,
        "api_key": os.environ.get("OCR_API_KEY"),
        "vlm_api_key": os.environ.get("VLM_API_KEY") or os.environ.get("OCR_API_KEY"),
        "api_auth_scheme": os.environ.get("OCR_API_AUTH_SCHEME", "Bearer"),
        "vlm_auth_scheme": os.environ.get("VLM_API_AUTH_SCHEME") or os.environ.get("OCR_API_AUTH_SCHEME", "Bearer"),
        "api_headers": _parse_headers("OCR_API_HEADERS"),
        "vlm_headers": _parse_headers("VLM_API_HEADERS") if os.environ.get("VLM_API_HEADERS") else _parse_headers("OCR_API_HEADERS"),
        "api_extra_payload": _parse_json_object("OCR_API_EXTRA_PAYLOAD"),
        "image_field": os.environ.get("OCR_API_IMAGE_FIELD", "image_base64"),
        "prompt_field": os.environ.get("OCR_API_PROMPT_FIELD", "prompt"),
        "model_field": os.environ.get("OCR_API_MODEL_FIELD", "model"),
        "vlm_endpoint": os.environ.get("VLM_API_URL") or endpoint,
        "vlm_model": os.environ.get("VLM_MODEL"),
        "timeout": float(os.environ.get("OCR_TIMEOUT", os.environ.get("NEMOTRON_OCR_TIMEOUT", "120"))),
    }


def _cache_path(image_path: Path, cache_dir: Path, config: dict[str, Any]) -> Path:
    digest = hashlib.sha256()
    digest.update(image_path.read_bytes())
    profile = {
        key: config.get(key)
        for key in (
            "provider", "model", "endpoint", "vlm_endpoint", "vlm_model",
            "api_key", "vlm_api_key", "api_headers", "vlm_headers",
            "api_extra_payload", "image_field", "prompt_field", "model_field",
        )
    }
    digest.update(json.dumps(profile, sort_keys=True).encode("utf-8"))
    return cache_dir / f"{digest.hexdigest()}.json"


def _normalise(payload: dict[str, Any]) -> dict[str, Any]:
    missing = [key for key in _REQUIRED_KEYS if key not in payload]
    if missing:
        raise ValueError(f"OCR response missing required fields: {', '.join(missing)}")
    result = {
        "markdown": str(payload["markdown"]),
        "bboxes": payload["bboxes"],
        "classes": payload["classes"],
        "confidence": payload["confidence"],
    }
    if payload.get("vlm_reasoning"):
        result["vlm_reasoning"] = payload["vlm_reasoning"]
    return result


def _tesseract_fallback(image_path: Path) -> dict[str, Any]:
    """Use local Tesseract when configured model OCR is unavailable."""
    try:
        import pytesseract
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError(
            "Model OCR is unavailable and local fallback requires pytesseract, "
            "Pillow, and the Tesseract executable."
        ) from exc

    try:
        with Image.open(image_path) as image:
            text = pytesseract.image_to_string(image, lang="eng").strip()
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Local Tesseract OCR failed for {image_path}: {exc}") from exc
    return {"markdown": text, "bboxes": [], "classes": [], "confidence": []}


def _multipart_body(image_path: Path) -> tuple[bytes, str]:
    boundary = "redblue-ocr-boundary"
    content = image_path.read_bytes()
    filename = image_path.name.replace('"', "")
    header = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode()
    return header + content + f"\r\n--{boundary}--\r\n".encode(), boundary


def _api_request(
    image_path: Path,
    prompt: str,
    config: dict[str, Any],
    *,
    task: str,
    model: str | None = None,
    ocr_text: str | None = None,
) -> dict[str, Any]:
    endpoint = config["vlm_endpoint"] if task == "reason" else config["endpoint"]
    payload: dict[str, Any] = dict(config["api_extra_payload"])
    payload.update({
        "task": task,
        config["model_field"]: model or config["model"],
        config["prompt_field"]: prompt,
        "mime_type": mimetypes.guess_type(image_path.name)[0] or "application/octet-stream",
        config["image_field"]: base64.b64encode(image_path.read_bytes()).decode("ascii"),
    })
    if ocr_text is not None:
        payload["ocr_text"] = ocr_text
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    headers.update(config["vlm_headers"] if task == "reason" else config["api_headers"])
    api_key = config.get("vlm_api_key") if task == "reason" else config.get("api_key")
    auth_scheme = config.get("vlm_auth_scheme") if task == "reason" else config.get("api_auth_scheme")
    if api_key and not any(name.lower() == "authorization" for name in headers):
        headers["Authorization"] = f"{auth_scheme} {api_key}".strip()
    req = request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with request.urlopen(req, timeout=config["timeout"]) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not isinstance(result, dict):
        raise ValueError("OCR API endpoint must return a JSON object")
    return result


def _chat_request(
    image_path: Path,
    prompt: str,
    config: dict[str, Any],
    model: str | None = None,
) -> str:
    provider = config["provider"]
    model = model or config["model"]
    if provider == "ollama":
        payload = {
            "model": model,
            "stream": False,
            "messages": [{
                "role": "user",
                "content": prompt,
                "images": [base64.b64encode(image_path.read_bytes()).decode("ascii")],
            }],
        }
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
    else:
        raise ValueError(f"Provider {provider!r} does not support chat completion")

    req = request.Request(
        config["endpoint"],
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with request.urlopen(req, timeout=config["timeout"]) as response:
        body = json.loads(response.read().decode("utf-8"))

    return str(body.get("message", {}).get("content", "")).strip()


def _run_model_ocr(image_path: Path, config: dict[str, Any]) -> dict[str, Any]:
    if config["provider"] == "api":
        return _normalise(_api_request(
            image_path,
            "Transcribe all legible text faithfully. Preserve useful line breaks; do not summarize or infer.",
            config,
            task="ocr",
        ))
    if config["provider"] == "nemotron":
        body, boundary = _multipart_body(image_path)
        req = request.Request(
            config["endpoint"],
            data=body,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Accept": "application/json",
            },
            method="POST",
        )
        with request.urlopen(req, timeout=config["timeout"]) as response:
            return _normalise(json.loads(response.read().decode("utf-8")))

    text = _chat_request(
        image_path,
        "Transcribe all legible text from this image faithfully. Preserve useful line breaks. "
        "Do not summarize, infer missing content, or add commentary.",
        config,
    )
    if not text:
        raise ValueError("OCR model returned empty text")
    return {"markdown": text, "bboxes": [], "classes": [], "confidence": []}


def _run_vlm_reasoning(
    image_path: Path,
    markdown: str,
    config: dict[str, Any],
) -> dict[str, str] | None:
    model = config.get("vlm_model")
    if not model or config["provider"] not in {"api", "ollama"}:
        return None

    prompt = (
        "Review this image and OCR transcript. Return JSON with keys reasoning and evidence_quote. "
        "Reason only from visible content, cite an exact non-empty quote from the OCR transcript, "
        "and do not infer unseen facts. If no quote supports a conclusion, return empty strings.\n"
        f"OCR transcript:\n{markdown[:6000]}"
    )
    try:
        if config["provider"] == "api":
            result = _api_request(
                image_path,
                prompt,
                config,
                task="reason",
                model=model,
                ocr_text=markdown[:6000],
            )
        else:
            raw = _chat_request(image_path, prompt, config, model=model)
            result = json.loads(raw)
        reasoning = result.get("reasoning")
        quote = result.get("evidence_quote")
        if (
            isinstance(reasoning, str)
            and reasoning.strip()
            and isinstance(quote, str)
            and quote.strip()
            and quote.casefold() in markdown.casefold()
        ):
            return {
                "reasoning": reasoning.strip()[:2000],
                "evidence_quote": quote,
                "status": "unverified",
            }
    except (error.URLError, TimeoutError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        logger.warning("Optional VLM reasoning failed: %s", exc)
    return None


@tool
def ocr_document(image_path: str | Path) -> dict[str, Any]:
    """OCR an image with a configured HTTP API or Ollama model."""
    path = Path(image_path)
    if not path.is_file():
        raise FileNotFoundError(f"OCR image does not exist: {path}")

    config = _provider_config()
    cache_dir = Path(os.environ.get("OCR_CACHE_DIR", os.environ.get("NEMOTRON_OCR_CACHE_DIR", _DEFAULT_CACHE_DIR)))
    cache_file = _cache_path(path, cache_dir, config)
    if cache_file.is_file():
        try:
            return _normalise(json.loads(cache_file.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, ValueError):
            cache_file.unlink(missing_ok=True)

    try:
        if config["provider"] == "tesseract":
            result = _tesseract_fallback(path)
        else:
            result = _run_model_ocr(path, config)
    except (error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
        logger.warning("Configured OCR provider failed; falling back to Tesseract: %s", exc)
        result = _tesseract_fallback(path)

    reasoning = _run_vlm_reasoning(path, result["markdown"], config)
    if reasoning:
        result["vlm_reasoning"] = reasoning

    result = _normalise(result)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result
