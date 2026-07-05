from __future__ import annotations

import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Thread-local PyMuPDF import to avoid import races
_tls = threading.local()

_TEXT_CACHE: dict[str, str] = {}  # pdf_path -> text
_TEXT_CACHE_LOCK = threading.Lock()
_TEXT_CACHE_MAX = 50


def _get_fitz():
    """Lazy-import fitz with thread-local caching."""
    if not hasattr(_tls, "fitz"):
        import fitz
        _tls.fitz = fitz
    return _tls.fitz


def _cache_key(pdf_path: str) -> str:
    return str(Path(pdf_path).resolve())


def cached_extract_text(pdf_path: str | Path) -> str:
    """Extract text with disk + memory caching.

    If a ``.txt`` sidecar file exists next to the PDF, it is returned
    directly without re-extracting.
    """
    pdf = Path(pdf_path)
    txt_cache = pdf.with_suffix(".txt")
    key = _cache_key(pdf_path)

    # Memory cache
    with _TEXT_CACHE_LOCK:
        if key in _TEXT_CACHE and _TEXT_CACHE[key]:
            return _TEXT_CACHE[key]

    # Disk cache
    if txt_cache.exists():
        text = txt_cache.read_text()
        with _TEXT_CACHE_LOCK:
            if len(_TEXT_CACHE) >= _TEXT_CACHE_MAX:
                _TEXT_CACHE.clear()
            _TEXT_CACHE[key] = text
        return text

    # Extract
    text = _extract_text_inner(pdf)
    if text:
        txt_cache.write_text(text)
        with _TEXT_CACHE_LOCK:
            if len(_TEXT_CACHE) >= _TEXT_CACHE_MAX:
                _TEXT_CACHE.clear()
            _TEXT_CACHE[key] = text
    return text


def _extract_text_inner(pdf_path: Path) -> str:
    """Core text extraction using PyMuPDF."""
    fitz = _get_fitz()
    doc = fitz.open(str(pdf_path))
    try:
        text = "\n".join(page.get_text() for page in doc)
    finally:
        doc.close()
    return text


def extract_text_parallel(
    pdf_paths: list[str | Path],
    max_workers: int = 4,
) -> dict[str, str]:
    """Extract text from multiple PDFs in parallel using a thread pool.

    Returns:
        Dict mapping str(pdf_path) -> extracted text.
    """
    results: dict[str, str] = {}
    lock = threading.Lock()

    def _extract_one(p: str | Path) -> None:
        text = cached_extract_text(p)
        with lock:
            results[str(p)] = text

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        pool.map(_extract_one, pdf_paths)

    return results

SECTION_HEADING = re.compile(
    r"^(#{1,3}\s+|\d+\.\d*\s+|[A-Z][A-Z\s]{2,}(?:\n|$))",
    re.MULTILINE,
)

REFERENCE_PATTERN = re.compile(
    r"\[(\d+)\]\s*(.*?)(?=\n\[\d+\]|\Z)", re.DOTALL
)

ARXIV_REF_PATTERN = re.compile(r"(\d{4}\.\d{4,5})")


def extract_text(pdf_path: str | Path) -> str:
    import fitz
    doc = fitz.open(str(pdf_path))
    text = "\n".join(page.get_text() for page in doc)
    doc.close()
    return text


def extract_metadata(pdf_path: str | Path) -> dict[str, Any]:
    import fitz
    doc = fitz.open(str(pdf_path))
    meta = doc.metadata or {}
    doc.close()
    return {
        "title": meta.get("title", ""),
        "author": meta.get("author", ""),
        "subject": meta.get("subject", ""),
    }


def extract_references(text: str) -> list[dict[str, str]]:
    refs = []
    for match in REFERENCE_PATTERN.finditer(text):
        refs.append({"num": match.group(1), "text": match.group(2).strip()})
    return refs


def extract_referenced_arxiv_ids(text: str) -> list[str]:
    return list(set(ARXIV_REF_PATTERN.findall(text)))


def _extract_caption(page: Any, image_rects: list[Any]) -> str:
    if not image_rects:
        return ""
    rect = image_rects[0]
    img_y1 = getattr(rect, 'y1', rect[3] if isinstance(rect, (list, tuple)) else 0)
    img_x0 = getattr(rect, 'x0', rect[0] if isinstance(rect, (list, tuple)) else 0)
    img_x1 = getattr(rect, 'x1', rect[2] if isinstance(rect, (list, tuple)) else 0)
    blocks = page.get_text("blocks")
    candidates = []
    for b in blocks:
        if len(b) < 5:
            continue
        bx0, by0, bx1, by1 = b[0], b[1], b[2], b[3]
        text = b[4].decode() if isinstance(b[4], bytes) else str(b[4])
        text = text.strip()
        if not text or len(text) < 5:
            continue
        if by0 > img_y1 and by0 - img_y1 < 150:
            if bx1 > img_x0 and bx0 < img_x1:
                candidates.append((by0 - img_y1, text))
        if img_y1 - by1 < 50 and img_y1 > by1:
            if bx1 > img_x0 and bx0 < img_x1:
                candidates.append((img_y1 - by1, text))
    candidates.sort(key=lambda x: x[0])
    for _, text in candidates:
        stripped = text.strip()
        if re.search(r'^(Fig(ure)?|Table|Algorithm|Algo\.)\s*\.?\s*\d', stripped, re.IGNORECASE):
            return stripped[:200]
    if candidates:
        return candidates[0][1][:200]
    return ""


def extract_images_from_pdf(pdf_path: str | Path, output_dir: str | Path) -> list[dict[str, Any]]:
    import fitz
    doc = fitz.open(str(pdf_path))
    images = []
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for page_num, page in enumerate(doc):
        image_list = page.get_images(full=True)
        for img_idx, img in enumerate(image_list):
            xref = img[0]
            base_image = doc.extract_image(xref)
            img_bytes = base_image["image"]
            w, h = base_image["width"], base_image["height"]
            if w < 100 or h < 100 or len(img_bytes) < 2048:
                continue
            ext = base_image["ext"]
            fname = f"figure_p{page_num+1:02d}_{img_idx+1:02d}.{ext}"
            path = output_dir / fname
            image_rects = page.get_image_rects(xref)
            caption = _extract_caption(page, image_rects)
            with open(path, "wb") as f:
                f.write(img_bytes)
            images.append({
                "filename": fname,
                "page": page_num + 1,
                "path": str(path),
                "ext": ext,
                "width": w,
                "height": h,
                "caption": caption,
            })
    doc.close()
    return images


def extract_sections(text: str) -> list[dict[str, Any]]:
    lines = text.split("\n")
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] = {"heading": "abstract", "content": []}
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if SECTION_HEADING.match(stripped):
            if current["content"]:
                sections.append(current)
            current = {"heading": stripped, "content": []}
        else:
            current["content"].append(stripped)
    if current["content"]:
        sections.append(current)
    for s in sections:
        s["content"] = "\n".join(s["content"])
    return sections
