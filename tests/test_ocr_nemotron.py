"""Contract tests for the Nemotron OCR adapter."""
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.ocr_nemotron import ocr_document


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
    monkeypatch.setenv("NEMOTRON_OCR_URL", "http://nemotron.local/parse")
    monkeypatch.setenv("NEMOTRON_OCR_CACHE_DIR", str(cache))

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(PAYLOAD).encode()

    with patch("tools.ocr_nemotron.request.urlopen", return_value=Response()) as urlopen:
        assert ocr_document(image) == PAYLOAD
        assert ocr_document(image) == PAYLOAD
        urlopen.assert_called_once()

    assert len(list(cache.glob("*.json"))) == 1


def test_ocr_document_requires_endpoint(tmp_path, monkeypatch):
    image = tmp_path / "page.png"
    image.write_bytes(b"image bytes")
    monkeypatch.delenv("NEMOTRON_OCR_URL", raising=False)
    with pytest.raises(RuntimeError, match="NEMOTRON_OCR_URL"):
        ocr_document(image)


def test_ocr_document_rejects_incomplete_response(tmp_path, monkeypatch):
    image = tmp_path / "page.png"
    image.write_bytes(b"image bytes")
    monkeypatch.setenv("NEMOTRON_OCR_URL", "http://nemotron.local/parse")

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"markdown": "only"}'

    with patch("tools.ocr_nemotron.request.urlopen", return_value=Response()):
        with pytest.raises(ValueError, match="missing required fields"):
            ocr_document(image)
