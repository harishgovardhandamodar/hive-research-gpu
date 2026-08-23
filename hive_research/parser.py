from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SECTION_HEADING = re.compile(
    r"^(#{1,3}\s+|\d+\.\d*\s+|[A-Z][A-Z\s]{2,}(?:\n|$))",
    re.MULTILINE,
)

REFERENCE_PATTERN = re.compile(
    r"\[(\d+)\]\s*(.*?)(?=\n\[\d+\]|\Z)", re.DOTALL
)

ARXIV_REF_PATTERN = re.compile(r"(\d{4}\.\d{4,5})")

CAPTION_PREFIX = re.compile(
    r'^(Fig(ure)?|Table|Algorithm|Algo\.|Listing)\s*\.?\s*\d+', re.IGNORECASE
)

# Noise thresholds for embedded raster extraction.
MIN_IMG_WIDTH = 120
MIN_IMG_HEIGHT = 80
MIN_IMG_BYTES = 2048

# A page must contain at least this many vector drawing ops to justify a
# full-page vector-render fallback (matplotlib plots easily produce 100+).
VECTOR_PAGE_MIN_DRAWINGS = 40


def content_hash(data: bytes) -> str:
    """Short content fingerprint used to deduplicate repeated images."""
    return hashlib.sha1(data).hexdigest()[:10]


def is_noise_image(width: int, height: int, nbytes: int) -> bool:
    """True for decorative junk: tiny logos, rules, gradient bars."""
    if width < MIN_IMG_WIDTH or height < MIN_IMG_HEIGHT:
        return True
    if nbytes < MIN_IMG_BYTES:
        return True
    # extreme aspect strips are usually headers/footers/underlines
    if max(width, height) / max(min(width, height), 1) > 25:
        return True
    return False


def pick_caption(
    text_blocks: list[Any],
    rect: tuple[float, float, float, float],
) -> str:
    """Choose the best caption text block near an image rect.

    Prefers blocks that start with 'Figure N'/'Table N' below the image;
    falls back to the closest overlapping block either side.
    """
    img_x0, img_y0, img_x1, img_y1 = rect
    candidates: list[tuple[float, str, bool]] = []
    for b in text_blocks:
        if len(b) < 5:
            continue
        bx0, by0, bx1, by1 = b[0], b[1], b[2], b[3]
        raw = b[4].decode() if isinstance(b[4], bytes) else str(b[4])
        text = raw.strip()
        if not text or len(text) < 5:
            continue
        overlaps_x = bx1 > img_x0 and bx0 < img_x1
        if not overlaps_x:
            continue
        if by0 >= img_y1 - 5:  # below the image
            gap = by0 - img_y1
            if gap < 150:
                candidates.append((gap, text, bool(CAPTION_PREFIX.match(text))))
        elif by1 <= img_y0 + 5:  # above the image
            gap = img_y0 - by1
            if gap < 60:
                candidates.append((gap, text, bool(CAPTION_PREFIX.match(text))))

    labeled = [c for c in candidates if c[2]]
    pool = labeled or candidates
    if not pool:
        return ""
    return sorted(pool, key=lambda x: x[0])[0][1][:200]


def _extract_caption(page: Any, image_rects: list[Any]) -> str:
    """Backward-compatible wrapper around pick_caption."""
    if not image_rects:
        return ""
    rect0 = image_rects[0]
    rect = (
        getattr(rect0, "x0", rect0[0] if isinstance(rect0, (list, tuple)) else 0),
        getattr(rect0, "y0", rect0[1] if isinstance(rect0, (list, tuple)) else 0),
        getattr(rect0, "x1", rect0[2] if isinstance(rect0, (list, tuple)) else 0),
        getattr(rect0, "y1", rect0[3] if isinstance(rect0, (list, tuple)) else 0),
    )
    return pick_caption(page.get_text("blocks"), rect)


def extract_images_from_pdf(
    pdf_path: str | Path,
    output_dir: str | Path,
    render_vector_pages: bool = True,
) -> list[dict[str, Any]]:
    """Extract meaningful figures from a PDF.

    Rasters are filtered for noise and deduplicated by content hash.
    For pages dominated by vector graphics with no usable raster, an
    optional full-page render keeps the visual content available for notes.
    """
    import fitz

    doc = fitz.open(str(pdf_path))
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    images: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    pages_with_raster: set[int] = set()

    for page_num, page in enumerate(doc):
        for img_idx, img in enumerate(page.get_images(full=True)):
            xref = img[0]
            try:
                base_image = doc.extract_image(xref)
            except Exception as e:
                logger.debug("Skipping unextractable xref %s: %s", xref, e)
                continue
            img_bytes = base_image["image"]
            w, h = base_image["width"], base_image["height"]
            if is_noise_image(w, h, len(img_bytes)):
                continue
            digest = content_hash(img_bytes)
            if digest in seen_hashes:
                logger.debug("Dropping duplicate image %s on page %d", digest, page_num + 1)
                continue
            seen_hashes.add(digest)

            ext = base_image["ext"]
            fname = f"figure_p{page_num+1:02d}_{img_idx+1:02d}_{digest}.{ext}"
            path = output_dir / fname
            path.write_bytes(img_bytes)
            rects = page.get_image_rects(xref)
            caption = _extract_caption(page, rects) if rects else ""
            images.append({
                "filename": fname,
                "page": page_num + 1,
                "path": str(path),
                "ext": ext,
                "width": w,
                "height": h,
                "caption": caption,
                "kind": "raster",
                "hash": digest,
            })
            pages_with_raster.add(page_num)

    if render_vector_pages:
        for page_num, page in enumerate(doc):
            if page_num in pages_with_raster:
                continue
            try:
                n_drawings = len(page.get_drawings())
            except Exception:
                continue
            if n_drawings < VECTOR_PAGE_MIN_DRAWINGS:
                continue
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            digest = content_hash(pix.tobytes("png"))
            if digest in seen_hashes:
                continue
            seen_hashes.add(digest)
            fname = f"figure_p{page_num+1:02d}_vector_{digest}.png"
            path = output_dir / fname
            pix.save(str(path))
            blocks = page.get_text("blocks")
            caption = pick_caption(blocks, (0, 0, page.rect.width, page.rect.height))
            images.append({
                "filename": fname,
                "page": page_num + 1,
                "path": str(path),
                "ext": "png",
                "width": pix.width,
                "height": pix.height,
                "caption": f"[page {page_num+1} vector figure] {caption}".strip(),
                "kind": "vector_render",
                "hash": digest,
            })

    doc.close()
    logger.info("Extracted %d figures from %s", len(images), pdf_path)
    return images


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
