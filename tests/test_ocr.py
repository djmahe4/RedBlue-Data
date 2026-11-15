"""Contract tests for configurable OCR providers."""
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.ocr import ocr_document


def _call_ocr(image):
    if hasattr(ocr_document, "invoke"):
        return ocr_document.invoke({"image_path": image})
    return ocr_document(image)


PAYLOAD = {
    "markdown": "# Finding\nText",
    "bboxes": [{"x": 1, "y": 2, "width": 3, "height": 4}],
    "classes": ["text"],
    "confidence": [0.98],
}


def test_ocr_document_posts_and_caches_result(tmp_path, monkeypatch):
    image = tmp_path / "page.png"
    image.write_bytes(b"image bytes")
    cache = tmp_path / "cache"
    monkeypatch.setenv("OCR_PROVIDER", "nemotron")
    monkeypatch.setenv("NEMOTRON_OCR_URL", "http://ocr.local/parse")
    monkeypatch.setenv("OCR_CACHE_DIR", str(cache))

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(PAYLOAD).encode()

    with patch("tools.ocr.request.urlopen", return_value=Response()) as urlopen:
        assert _call_ocr(image) == PAYLOAD
        assert _call_ocr(image) == PAYLOAD
        urlopen.assert_called_once()

    assert len(list(cache.glob("*.json"))) == 1


def test_ocr_document_falls_back_to_tesseract_without_endpoint(tmp_path, monkeypatch):
    image = tmp_path / "page.png"
    image.write_bytes(b"image bytes")
    cache = tmp_path / "cache"
    monkeypatch.setenv("OCR_PROVIDER", "tesseract")
    monkeypatch.delenv("NEMOTRON_OCR_URL", raising=False)
    monkeypatch.setenv("OCR_CACHE_DIR", str(cache))
    fallback = {"markdown": "local OCR", "bboxes": [], "classes": [], "confidence": []}

    with patch("tools.ocr._tesseract_fallback", return_value=fallback) as tesseract:
        assert _call_ocr(image) == fallback
        assert _call_ocr(image) == fallback
        tesseract.assert_called_once_with(image)


def test_malformed_provider_response_falls_back_to_tesseract(tmp_path, monkeypatch):
    image = tmp_path / "page.png"
    image.write_bytes(b"image bytes")
    monkeypatch.setenv("OCR_PROVIDER", "nemotron")
    monkeypatch.setenv("NEMOTRON_OCR_URL", "http://ocr.local/parse")
    fallback = {"markdown": "local OCR", "bboxes": [], "classes": [], "confidence": []}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"markdown": "only"}'

    with patch("tools.ocr.request.urlopen", return_value=Response()):
        with patch("tools.ocr._tesseract_fallback", return_value=fallback):
            assert _call_ocr(image) == fallback


def test_generic_api_uses_configured_url_headers_and_payload(tmp_path, monkeypatch):
    image = tmp_path / "page.png"
    image.write_bytes(b"image bytes")
    monkeypatch.setenv("OCR_PROVIDER", "api")
    monkeypatch.setenv("OCR_API_URL", "https://ocr.example.test/v1/parse")
    monkeypatch.setenv("OCR_MODEL", "ocr-model")
    monkeypatch.setenv("OCR_API_KEY", "secret")
    monkeypatch.setenv("OCR_API_AUTH_SCHEME", "Token")
    monkeypatch.setenv("OCR_API_HEADERS", '{"X-Workspace": "redblue"}')
    monkeypatch.setenv("OCR_API_EXTRA_PAYLOAD", '{"language": "eng"}')
    monkeypatch.setenv("OCR_CACHE_DIR", str(tmp_path / "cache"))

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(PAYLOAD).encode()

    with patch("tools.ocr.request.urlopen", return_value=Response()) as urlopen:
        assert _call_ocr(image) == PAYLOAD
    req = urlopen.call_args.args[0]
    body = json.loads(req.data)
    assert req.full_url == "https://ocr.example.test/v1/parse"
    assert req.get_header("Authorization") == "Token secret"
    assert req.get_header("X-workspace") == "redblue"
    assert body["model"] == "ocr-model"
    assert body["language"] == "eng"
    assert body["image_base64"]


def test_ollama_ocr_uses_native_chat_endpoint(tmp_path, monkeypatch):
    image = tmp_path / "page.png"
    image.write_bytes(b"image bytes")
    monkeypatch.setenv("OCR_PROVIDER", "ollama")
    monkeypatch.setenv("OCR_MODEL", "qwen-vl")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.local:11434")
    monkeypatch.setenv("OCR_CACHE_DIR", str(tmp_path / "cache"))

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"message":{"content":"recognized text"}}'

    with patch("tools.ocr.request.urlopen", return_value=Response()) as urlopen:
        result = _call_ocr(image)
    req = urlopen.call_args.args[0]
    body = json.loads(req.data)
    assert req.full_url == "http://ollama.local:11434/api/chat"
    assert body["model"] == "qwen-vl"
    assert result["markdown"] == "recognized text"


def test_optional_vlm_reasoning_requires_verbatim_ocr_quote(tmp_path, monkeypatch):
    image = tmp_path / "page.png"
    image.write_bytes(b"image bytes")
    monkeypatch.setenv("OCR_PROVIDER", "api")
    monkeypatch.setenv("OCR_API_URL", "http://ocr.local/parse")
    monkeypatch.setenv("OCR_MODEL", "ocr-model")
    monkeypatch.setenv("VLM_MODEL", "reasoning-model")
    monkeypatch.setenv("OCR_CACHE_DIR", str(tmp_path / "cache"))

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(self.payload).encode()

    reasoning = {"reasoning": "Text identifies a finding.", "evidence_quote": "Finding"}
    with patch(
        "tools.ocr.request.urlopen",
        side_effect=[Response(PAYLOAD), Response(reasoning)],
    ) as urlopen:
        result = _call_ocr(image)
    assert urlopen.call_count == 2
    assert result["vlm_reasoning"]["status"] == "unverified"
    assert result["vlm_reasoning"]["evidence_quote"] == "Finding"
