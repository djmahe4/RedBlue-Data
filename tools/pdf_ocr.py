"""Render PDF pages and OCR clustered visual regions with the shared OCR adapter."""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, cast

import fitz

try:
    from langchain_core.tools import tool
except ImportError:  # Keep optional LangChain out of the base harness dependency.
    def tool(func):  # type: ignore[no-untyped-def]
        return func


PROXIMITY_GAP_PT = 40.0
MERGE_RATIO_THRESHOLD = 0.40
MIN_FIGURE_AREA_RATIO = 0.005
MIN_DRAWING_DIM_PT = 20.0
MAX_IMAGE_BLOCKS = 2


def _area(rect: list[float]) -> float:
    return max(0.0, (rect[2] - rect[0]) * (rect[3] - rect[1]))


def _union_rect(left: list[float], right: list[float]) -> list[float]:
    return [
        min(left[0], right[0]), min(left[1], right[1]),
        max(left[2], right[2]), max(left[3], right[3]),
    ]


def _gap_between(left: list[float], right: list[float]) -> float:
    gap_x = max(0.0, max(left[0], right[0]) - min(left[2], right[2]))
    gap_y = max(0.0, max(left[1], right[1]) - min(left[3], right[3]))
    return max(gap_x, gap_y)


def _collect_figure_rects(page: fitz.Page, min_area: float) -> list[list[float]]:
    """Collect significant embedded image and vector-drawing rectangles."""
    page_rect = page.rect
    page_area = max(1.0, page_rect.width * page_rect.height)
    rects: list[list[float]] = []

    for image_info in page.get_images(full=True):
        xref = image_info[0]
        try:
            for rect in page.get_image_rects(xref):
                clipped = rect & page_rect
                coords = [clipped.x0, clipped.y0, clipped.x1, clipped.y1]
                area = _area(coords)
                if clipped.width < 40 or clipped.height < 40 or area < min_area:
                    continue
                if area / page_area > 0.85:
                    continue
                rects.append([round(value, 2) for value in coords])
        except Exception:  # malformed or unsupported image placement
            continue

    try:
        drawings = page.get_drawings()
    except Exception:
        drawings = []
    for drawing in drawings:
        raw_rect = drawing.get("rect")
        if raw_rect is None:
            continue
        clipped = fitz.Rect(raw_rect) & page_rect
        coords = [clipped.x0, clipped.y0, clipped.x1, clipped.y1]
        area = _area(coords)
        if clipped.width < 40 or clipped.height < 55 or area < min_area:
            continue
        if area / page_area > 0.85:
            continue
        rects.append([round(value, 2) for value in coords])

    unique: list[list[float]] = []
    seen: set[tuple[float, ...]] = set()
    for rect in rects:
        key = tuple(rect)
        if key not in seen:
            seen.add(key)
            unique.append(rect)
    return unique


def _cluster_rects(rects: list[list[float]], gap_threshold: float) -> list[list[float]]:
    """Merge spatially close boxes using greedy single-linkage clustering."""
    clusters = [list(rect) for rect in rects]
    changed = True
    while changed:
        changed = False
        merged: list[list[float]] = []
        used = [False] * len(clusters)
        for index, current in enumerate(clusters):
            if used[index]:
                continue
            current = list(current)
            for other_index in range(index + 1, len(clusters)):
                if used[other_index]:
                    continue
                if _gap_between(current, clusters[other_index]) <= gap_threshold:
                    current = _union_rect(current, clusters[other_index])
                    used[other_index] = True
                    changed = True
            merged.append(current)
            used[index] = True
        clusters = merged
    return clusters


def _select_regions(rects: list[list[float]], page_area: float) -> list[list[float]]:
    clusters = sorted(_cluster_rects(rects, PROXIMITY_GAP_PT), key=_area, reverse=True)
    if len(clusters) < 2:
        return clusters[:MAX_IMAGE_BLOCKS]
    combined = _union_rect(clusters[0], clusters[1])
    if page_area and _area(combined) / page_area <= MERGE_RATIO_THRESHOLD:
        return [combined]
    return clusters[:MAX_IMAGE_BLOCKS]


def _call_ocr(image_path: Path) -> dict[str, Any]:
    from tools.ocr import ocr_document

    invoke = getattr(ocr_document, "invoke", None)
    if callable(invoke):
        return invoke({"image_path": str(image_path)})
    if callable(ocr_document):
        return cast(dict[str, Any], ocr_document(str(image_path)))
    raise RuntimeError("OCR adapter is not callable")


def _unique_lines(chunks: list[str]) -> str:
    lines: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        for line in chunk.splitlines():
            normalized = " ".join(line.split()).casefold()
            if normalized and normalized not in seen:
                seen.add(normalized)
                lines.append(line.strip())
    return "\n".join(lines)


def ocr_pdf_page(pdf_path: Path | str, page_number: int = 1) -> dict[str, Any]:
    """OCR a page screenshot plus up to two clustered visual crops."""
    path = Path(pdf_path)
    if page_number < 1:
        raise ValueError("page_number is one-based and must be positive")
    if not path.is_file():
        raise FileNotFoundError(f"PDF does not exist: {path}")

    with fitz.open(path) as document:
        if page_number > len(document):
            raise ValueError(f"page_number {page_number} exceeds PDF page count {len(document)}")
        page = document[page_number - 1]
        page_area = max(1.0, page.rect.width * page.rect.height)
        page_text = page.get_text().strip()
        regions = _select_regions(
            _collect_figure_rects(page, page_area * MIN_FIGURE_AREA_RATIO),
            page_area,
        )
        with tempfile.TemporaryDirectory(prefix="redblue-pdf-ocr-") as temporary_dir:
            page_image = Path(temporary_dir) / "page.png"
            page.get_pixmap(dpi=150, alpha=False).save(str(page_image))
            chunks = [page_text]
            vision: list[dict[str, Any]] = []
            full_page_result = _call_ocr(page_image)
            chunks.append(str(full_page_result.get("markdown") or ""))
            if full_page_result.get("vlm_reasoning"):
                vision.append({"region": "page", **full_page_result["vlm_reasoning"]})

            block_results: list[dict[str, Any]] = []
            for index, rect in enumerate(regions):
                crop_image = Path(temporary_dir) / f"region-{index}.png"
                fitz_rect = fitz.Rect(rect)
                dpi = 300 if fitz_rect.width < 180 or fitz_rect.height < 180 else 150
                page.get_pixmap(clip=fitz_rect, dpi=dpi, alpha=False).save(str(crop_image))
                result = _call_ocr(crop_image)
                chunks.append(str(result.get("markdown") or ""))
                if result.get("vlm_reasoning"):
                    vision.append({"region": index, **result["vlm_reasoning"]})
                block_results.append({"rect": rect, "markdown": result.get("markdown", "")})

    coverage = min(1.0, sum(_area(region) for region in regions) / page_area)
    response: dict[str, Any] = {
        "markdown": _unique_lines(chunks),
        "page_text": page_text,
        "page_number": page_number,
        "image_coverage_ratio": round(coverage, 4),
        "image_blocks": block_results,
    }
    if vision:
        response["vlm_reasoning"] = vision
    return response


@tool
def ocr_pdf_document(pdf_path: str, page_number: int = 1) -> dict[str, Any]:
    """OCR a PDF page and inspect clustered figure/image regions."""
    return ocr_pdf_page(pdf_path, page_number)
