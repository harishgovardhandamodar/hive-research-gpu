"""Awesome-AI-Scientist integration: curated research-automation excerpts.

Fetches the README of harishgovardhandamodar/Awesome-AI-Scientist and parses it
into structured excerpts (paper bullets with arxiv id, year-month, section
path, review links) plus the featured agent/tool projects. Cached on disk so
the tab works offline after the first sync.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

FORK_URL = "https://raw.githubusercontent.com/harishgovardhandamodar/Awesome-AI-Scientist/main/README.md"
REPO_URL = "https://github.com/harishgovardhandamodar/Awesome-AI-Scientist"

_ARXIV_IN_URL = re.compile(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})(v\d+)?")
_YEAR_BADGE = re.compile(r"arXiv-(\d{4})\.(\d{2})")
_MD_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def _cache_path(data_dir: str | Path | None) -> Path:
    base = Path(data_dir) if data_dir else Path("data/companion")
    return base / "awesome_scientist_cache.json"


def load_cached(data_dir: str | Path | None = None) -> dict[str, Any]:
    path = _cache_path(data_dir)
    if not path.exists() and (alt := path.parent / "awesome_scientist_cache.json").exists():
        path = alt
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text())
        if isinstance(raw, dict):
            return raw
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def save_cache(payload: dict[str, Any], data_dir: str | Path | None) -> Path:
    path = _cache_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=1))
    os.replace(tmp, path)
    return path


def _clean(text: str) -> str:
    text = _MD_LINK.sub(r"\1", text)          # [x](y) -> x
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)  # badges/images out
    text = re.sub(r"\s+", " ", text).strip()
    return text.rstrip("-–— ").rstrip()


def parse_readme(md: str) -> dict[str, Any]:
    """Parse the awesome-list into excerpts + featured agent/tool projects."""
    excerpts: list[dict[str, Any]] = []
    agents: list[dict[str, Any]] = []
    section: list[str] = []

    in_projects_table = False
    for line in md.splitlines():
        stripped = line.strip()

        # track section ancestry via headings
        m = re.match(r"^(#{2,4})\s+(.*)$", stripped)
        if m:
            level, title = len(m.group(1)), _clean(m.group(2))
            title = re.sub(r"^\d+(\.\d+)*\.?\s*", "", title)  # strip 1.2.3 numbering
            section = section[: level - 2] + [title]
            in_projects_table = False

        if stripped.startswith("|") and "Project |" in stripped:
            in_projects_table = True
            continue
        if stripped.startswith("|--") or stripped.startswith("| --"):
            continue

        # featured projects table rows → agent/tool entries
        if in_projects_table and stripped.startswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if len(cells) >= 4:
                name_m = _MD_LINK.search(cells[0])
                url_m = _MD_LINK.search(cells[3])
                if name_m:
                    agents.append(
                        {
                            "name": _clean(name_m.group(1)),
                            "description": _clean(cells[1]),
                            "url": url_m.group(2) if url_m else "",
                            "kind": "open-source",
                        }
                    )
            continue

        # commercial platform bullets → tools too
        if stripped.startswith("*") and stripped.endswith(")") and "Platform" not in stripped:
            links = _MD_LINK.findall(stripped)
            if links:
                name, url = links[0]
                note = _clean(stripped.lstrip("* "))
                agents.append({"name": _clean(name), "description": note, "url": url, "kind": "platform"})
            continue

        # paper excerpt bullets
        if not stripped.startswith("-"):
            continue
        body = stripped.lstrip("- ").strip()
        paper_url = ""
        pm = re.search(r"\[+\s*Paper\s*\]+\((https?://[^)]+)\)", body, re.IGNORECASE)
        if pm:
            paper_url = pm.group(1)
        review_url = ""
        rm = re.search(r"\[+(?:AI Review|Review)\]+\((https?://[^)]+)\)", body, re.IGNORECASE)
        if rm:
            review_url = rm.group(1)
        year = month = ""
        ym = _YEAR_BADGE.search(body)
        if ym:
            year, month = ym.group(1), ym.group(2)
        arxiv_id = ""
        am = _ARXIV_IN_URL.search(paper_url)
        if am:
            arxiv_id = am.group(1)
        title = _clean(body.split("[Paper]", 1)[0])[:200]
        if not title or (not paper_url and not arxiv_id):
            continue
        excerpts.append(
            {
                "title": title,
                "url": paper_url,
                "arxiv_id": arxiv_id,
                "year": year,
                "month": month,
                "section": " › ".join(s for s in section if s),
                "review_url": review_url,
                "reviewed": bool(review_url),
            }
        )

    return {
        "excerpts": excerpts,
        "agents": agents,
        "sections": sorted({e["section"] for e in excerpts}),
    }


async def fetch_and_cache(data_dir: str | Path | None = None, url: str = FORK_URL) -> dict[str, Any]:
    """Sync from the fork; falls back to urllib like agents_fork."""

    def _fetch_sync() -> str:
        try:
            import httpx

            resp = httpx.get(url, timeout=25, follow_redirects=True)
            resp.raise_for_status()
            return resp.text
        except Exception:
            import urllib.request

            req = urllib.request.Request(url, headers={"User-Agent": "fox-companion"})
            with urllib.request.urlopen(req, timeout=25) as r:  # noqa: S310
                return r.read().decode("utf-8", errors="replace")

    import asyncio

    md = await asyncio.to_thread(_fetch_sync)
    parsed = parse_readme(md)
    payload = {
        "source": REPO_URL,
        "fetched_at": time.time(),
        **parsed,
    }
    save_cache(payload, data_dir)
    return payload
