"""Discovery & retrieval helpers: watch-pool browsing, library search joins,
and vault-path conversion for the artifact viewer."""

from __future__ import annotations

from typing import Any

VAULT_PREFIX = "data/vault/"


def vault_to_viewer_path(note_path: str | None) -> str | None:
    """'data/vault/<folder>/00_notes.md' -> 'Notes/<folder>/00_notes.md'."""
    if not note_path:
        return None
    if note_path.startswith(VAULT_PREFIX):
        return "Notes/" + note_path[len(VAULT_PREFIX):]
    if note_path.startswith("Notes/"):
        return note_path
    return None


def trim(text: Any, n: int) -> str:
    text = str(text or "")
    return text[: n - 1] + "…" if len(text) > n else text


def shape_pool_paper(p: dict[str, Any]) -> dict[str, Any]:
    return {
        "arxiv_id": p.get("arxiv_id", ""),
        "title": trim(p.get("title"), 160),
        "authors": trim(p.get("authors_str"), 120),
        "published": p.get("published", ""),
        "abstract": trim(p.get("abstract"), 420),
        "topics": p.get("topics", []),
        "imported": bool(p.get("imported")),
    }


def join_note_paths(search_hits: list[dict[str, Any]], papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach a viewer-readable note path to local search hits when one exists."""
    by_id_prefix: dict[str, dict[str, str]] = {}
    for p in papers:
        pid = str(p.get("id", ""))
        base = pid.split("v")[0]
        if base:
            by_id_prefix.setdefault(base, p)
    out = []
    for hit in search_hits:
        hid = str(hit.get("arxiv_id", ""))
        base = hid.split("v")[0]
        paper = by_id_prefix.get(base)
        out.append(
            {
                "arxiv_id": hid,
                "title": trim(hit.get("title"), 160),
                "authors": trim(hit.get("authors"), 140),
                "published": hit.get("published", ""),
                "abstract": trim(hit.get("abstract"), 320),
                "note_path": vault_to_viewer_path(paper.get("note_path")) if paper else None,
            }
        )
    return out
