import sys
from pathlib import Path
from unittest.mock import patch

import fitz

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.pdf_ocr import _cluster_rects, ocr_pdf_page


def test_cluster_rects_merges_nearby_visual_regions():
    clusters = _cluster_rects([[0, 0, 30, 30], [50, 0, 80, 30], [300, 300, 350, 350]], 25)
    assert clusters == [[0, 0, 80, 30], [300, 300, 350, 350]]


def test_pdf_page_crops_visuals_and_deduplicates_ocr_text(tmp_path):
    pdf_path = tmp_path / "visuals.pdf"
    document = fitz.open()
    page = document.new_page(width=600, height=800)
    page.insert_text((40, 40), "Evidence title")
    page.draw_rect(fitz.Rect(40, 100, 180, 240), color=(0, 0, 0))
    document.save(pdf_path)
    document.close()

    def fake_ocr(image_path):
        return {
            "markdown": "Evidence title\nOCR figure text",
            "vlm_reasoning": {
                "reasoning": "Figure mentions a test value.",
                "evidence_quote": "OCR figure text",
                "status": "unverified",
            },
        }

    with patch("tools.pdf_ocr._call_ocr", side_effect=fake_ocr) as ocr:
        result = ocr_pdf_page(pdf_path, 1)

    assert ocr.call_count == 2  # rendered page and one clustered crop
    assert result["markdown"].count("Evidence title") == 1
    assert result["image_blocks"][0]["rect"] == [40.0, 100.0, 180.0, 240.0]
    assert result["vlm_reasoning"][0]["status"] == "unverified"
