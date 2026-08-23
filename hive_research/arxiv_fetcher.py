from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import arxiv

logger = logging.getLogger(__name__)

ARXIV_ID_PATTERN = re.compile(
    r"(?:\barxiv\.org/(?:abs|pdf)/)?"
    r"("
    r"\d{4}\.\d{4,5}(?:v\d+)?"        # new style: 2401.12345, 2401.12345v2
    r"|[a-z-]+(?:\.[A-Z]{2})?/\d{7}"  # old style: cs/0703125, math.GT/0309136
    r")",
    re.IGNORECASE,
)


def parse_arxiv_id(text: str) -> str | None:
    m = ARXIV_ID_PATTERN.search(text)
    if not m:
        return None
    arxiv_id = m.group(1)
    # Strip version suffix so v1/v2 dedupe to one graph node.
    return re.sub(r"v\d+$", "", arxiv_id)


def extract_arxiv_ids(text: str) -> list[str]:
    return ARXIV_ID_PATTERN.findall(text)


class PaperInfo:
    def __init__(self, result: arxiv.Result) -> None:
        self.entry_id: str = result.entry_id
        self.arxiv_id: str = result.get_short_id()
        self.title: str = result.title
        self.authors: list[dict[str, Any]] = [
            {"name": a.name, "affiliations": a.affiliation} for a in result.authors
        ]
        self.authors_str: str = ", ".join(a["name"] for a in self.authors)
        self.affiliations_str: str = "; ".join(
            ", ".join(a["affiliations"]) for a in self.authors if a["affiliations"]
        )
        self.abstract: str = result.summary
        self.published: str = result.published.strftime("%Y-%m-%d") if result.published else ""
        self.updated: str = result.updated.strftime("%Y-%m-%d") if result.updated else ""
        self.categories: list[str] = result.categories
        self.pdf_url: str = str(result.pdf_url)
        self.links: list[dict[str, str]] = [
            {"href": l.href, "title": l.title} for l in result.links
        ]


def search_arxiv(query: str, max_results: int = 10) -> list[PaperInfo]:
    client = arxiv.Client(delay_seconds=6, num_retries=8, page_size=min(max_results, 100))
    search = arxiv.Search(query=query, max_results=max_results)
    return [PaperInfo(r) for r in client.results(search)]


def fetch_by_id(arxiv_id: str) -> PaperInfo | None:
    client = arxiv.Client(delay_seconds=6, num_retries=8)
    try:
        search = arxiv.Search(id_list=[arxiv_id])
        results = list(client.results(search))
        return PaperInfo(results[0]) if results else None
    except Exception as e:
        logger.error("Failed to fetch arXiv id %s: %s", arxiv_id, e)
        return None


def fetch_by_id_with_meta(arxiv_id: str) -> dict[str, Any]:
    paper = fetch_by_id(arxiv_id)
    if paper is None:
        return {"status": "error", "message": f"arXiv API unreachable or rate-limited for {arxiv_id}"}
    return {"status": "ok", "paper": paper}


def download_pdf(arxiv_id: str, target_dir: str | Path) -> Path | None:
    """Download a paper PDF atomically.

    Content is validated (PDF magic bytes) and written to a .part file that
    is renamed into place — an interrupted download must never leave a
    truncated file that later poisons parsing/analysis/RAG.
    """
    import os

    import requests as req

    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    target_path = target_dir / f"{arxiv_id}.pdf"
    part_path = target_dir / f"{arxiv_id}.pdf.part"
    try:
        resp = req.get(pdf_url, timeout=60, headers={
            "User-Agent": "hive-research-gpu/0.2.0 (mailto:research@example.com)"
        })
        resp.raise_for_status()
        data = resp.content
        if not data.startswith(b"%PDF"):
            logger.error("Downloaded %s is not a valid PDF (%d bytes, bad magic)", arxiv_id, len(data))
            return None
        if len(data) < 10240:
            logger.error("Downloaded %s suspiciously small (%d bytes) — rejecting", arxiv_id, len(data))
            return None
        part_path.write_bytes(data)
        os.replace(part_path, target_path)
        return target_path
    except Exception as e:
        logger.error("Failed to download PDF for %s: %s", arxiv_id, e)
        try:
            part_path.unlink(missing_ok=True)
        except Exception:
            pass
        return None
