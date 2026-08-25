"""BibTeX export for library and pool papers."""

from __future__ import annotations

import re
from typing import Any


def _clean(text: str) -> str:
    return re.sub(r"[{}]", "", str(text)).strip()


def _key(arxiv_id: str, authors: str, year: str) -> str:
    first_surname = "unknown"
    if authors:
        first = _clean(authors).split(",")[0].split("and")[0].strip().split()
        if first:
            first_surname = first[-1].lower()
    # bibtex keys should stay alphanumeric; "n.d." years and unicode names
    # would otherwise leak dots/spaces into the key
    year_part = re.sub(r"[^a-zA-Z0-9]", "", year) or "nd"
    ident = re.sub(r"[^a-zA-Z0-9]", "", arxiv_id.split("v")[0])
    return f"{first_surname}{year_part}{ident}"


def bibtex(arxiv_id: str, title: str, authors: str, published: str) -> str:
    arxiv_id = _clean(arxiv_id)
    title = _clean(title) or arxiv_id
    year = (published or "")[:4] or "n.d."
    author_list = " and ".join(a.strip() for a in _clean(authors).split(",") if a.strip()) or "Unknown"
    key = _key(arxiv_id, authors, year)
    return (
        f"@article{{{key},\n"
        f"  title = {{{title}}},\n"
        f"  author = {{{author_list}}},\n"
        f"  year = {{{year}}},\n"
        f"  eprint = {{{arxiv_id}}},\n"
        f"  archivePrefix = {{arXiv}},\n"
        f"  url = {{https://arxiv.org/abs/{arxiv_id.split('v')[0]}}}\n"
        f"}}"
    )


def topic_drift(current: dict[str, float], baseline: dict[str, float], threshold: float = 0.08) -> list[dict[str, Any]]:
    """Biggest share changes between two topic-share distributions."""
    keys = set(current) | set(baseline)
    deltas = []
    for k in keys:
        delta = current.get(k, 0.0) - baseline.get(k, 0.0)
        deltas.append({"topic": k, "delta": round(delta, 4), "direction": "rising" if delta > 0 else "falling"})
    deltas.sort(key=lambda d: (0 if d["direction"] == "rising" else 1, -abs(d["delta"])))
    return [d for d in deltas if abs(d["delta"]) >= threshold]
