"""The repository documentation set, served as selectable documents to the About tab.

Mirrors the design-doc rail in ``agentic-knowledge-mapper``: a small viewer that
lists the Markdown already in the repo and renders one on click. It does not
author the documents and does not copy them into the database.

Two properties matter more than the feature:

* **The index is built from a scan, and the id is not a path.** A document is
  reachable only if its id appears in the scan; the file is then re-checked with
  ``realpath`` against the roots it may come from. A caller cannot reach an
  arbitrary file by passing a path, so a traversal attempt is a 404 like any
  other unknown id -- there is no code path that turns user input into a path.
* **A missing docs directory is a state, not a crash.** The docs are
  documentation; an image built without them should show an explanation, not a
  500. ``available: false`` with a reason is the honest answer.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

#: Repository root, i.e. the parent of the ``hive_research`` package.
REPO_ROOT = Path(__file__).resolve().parent.parent

DOCS_DIR = Path(os.environ.get("HIVE_DOCS_DIR") or (REPO_ROOT / "docs"))

#: Safety valve. The largest document here is well under this; hitting it means
#: something is wrong with the file, not that the tab should refuse to render.
MAX_BYTES = 1_000_000

#: Root-level files that are part of the documentation set, in reading order.
_ROOT_FILES: list[tuple[str, str]] = [
    ("readme", "README.md"),
    ("agents", "AGENTS.md"),
]

#: Human titles for filenames whose stem reads poorly once title-cased.
_TITLE_OVERRIDES: dict[str, str] = {
    "readme": "README",
    "agents": "AGENTS.md",
    "api": "HTTP API",
    "cli": "Command line",
    "rag": "Retrieval (RAG)",
    "gpu": "GPU scheduling",
    "docker": "Docker & deployment",
    "SUMMARY": "Summary",
}

_HEADING_RE = re.compile(r"^\s*#\s+(.+?)\s*$", re.MULTILINE)


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _group_for(path: Path, stem: str) -> str:
    """Root files are the repository set; overview docs lead; the rest are reference."""
    try:
        is_root = path.resolve().parent == REPO_ROOT.resolve()
    except OSError:
        is_root = False
    if is_root:
        return "Repository"
    if stem in ("README", "SUMMARY"):
        return "Start here"
    return "Documentation"


def _candidates() -> list[dict[str, Any]]:
    """Every documentation file, in reading order, with its stable id.

    Root files first, then ``docs/`` sorted, with ``README``/``SUMMARY`` pulled
    ahead of the rest. A missing ``docs/`` directory yields just the root files,
    which is why this returns what exists rather than raising.
    """
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for doc_id, name in _ROOT_FILES:
        path = REPO_ROOT / name
        if path.is_file():
            out.append({"id": doc_id, "file": name, "path": path})
            seen.add(doc_id)

    if DOCS_DIR.is_dir():
        stems = sorted(p.stem for p in DOCS_DIR.glob("*.md"))
        # Start-here documents first; everything else keeps alphabetical order.
        priority = {"README": 0, "SUMMARY": 1}
        stems.sort(key=lambda s: (priority.get(s, 5), s.lower()))
        for stem in stems:
            name = f"{stem}.md"
            doc_id = _slug(stem)
            if doc_id in seen:
                doc_id = f"docs-{doc_id}"
            seen.add(doc_id)
            out.append({"id": doc_id, "file": name, "path": DOCS_DIR / name})

    for entry in out:
        entry["title"] = _TITLE_OVERRIDES.get(entry["file"].removesuffix(".md"), "")
        if not entry["title"]:
            entry["title"] = entry["file"][:-3].replace("-", " ").replace("_", " ").title()
        entry["group"] = _group_for(entry["path"], entry["file"].removesuffix(".md"))
    return out


def _entry(doc_id: str) -> Optional[dict[str, Any]]:
    want = str(doc_id or "")
    for entry in _candidates():
        if entry["id"] == want:
            return entry
    return None


def _allowed_roots() -> list[str]:
    roots = [str(REPO_ROOT.resolve())]
    if DOCS_DIR.exists():
        roots.append(str(DOCS_DIR.resolve()))
    return roots


def _resolve(doc_id: str) -> dict[str, Any]:
    """Map an id to its file, refusing anything outside the documentation roots.

    The id is the only caller-controlled input and it is looked up in the scan,
    so the resolved path is already determined here. The ``realpath`` check is
    not load-bearing today; it is here so a future index sourced from
    configuration cannot quietly turn this into a read-anything route.
    """
    entry = _entry(doc_id)
    if entry is None:
        raise KeyError(doc_id)
    real = os.path.realpath(str(entry["path"]))
    if not real.endswith(".md"):
        raise KeyError(doc_id)
    if not any(real == r or real.startswith(r + os.sep)
               for r in _allowed_roots()):
        raise KeyError(doc_id)
    if not os.path.isfile(real):
        raise FileNotFoundError(entry["file"])
    entry = dict(entry, path=real)
    return entry


def _first_heading(path: str) -> str:
    """The document's H1, if it has one. Bounded read: only the top of the file."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            head = fh.read(4096)
    except OSError:
        return ""
    m = _HEADING_RE.search(head)
    return m.group(1).strip() if m else ""


def _safe_read(path: str) -> tuple[str, bool]:
    """Read a file, capping the size. Returns ``(text, truncated)``."""
    with open(path, "rb") as fh:
        raw = fh.read(MAX_BYTES)
        truncated = len(raw) == MAX_BYTES and bool(fh.read(1))
    return raw.decode("utf-8", errors="replace"), truncated


def _stat(entry: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {k: entry[k] for k in ("id", "file", "title", "group")}
    try:
        resolved = _resolve(entry["id"])
        st = os.stat(resolved["path"])
        heading = _first_heading(resolved["path"])
    except (KeyError, OSError):
        out.update(available=False, bytes=0, mtime=None, title=entry["title"])
        return out
    out.update(available=True, bytes=st.st_size, mtime=_iso(st.st_mtime),
               title=heading or entry["title"])
    return out


def list_docs() -> dict[str, Any]:
    """Every document in the set, in reading order, with its metadata."""
    available = DOCS_DIR.is_dir()
    docs = [_stat(entry) for entry in _candidates()]
    groups: list[str] = []
    for d in docs:
        if d["group"] not in groups:
            groups.append(d["group"])
    out: dict[str, Any] = {
        "source": str(DOCS_DIR.relative_to(REPO_ROOT)) if available else str(DOCS_DIR),
        "available": available,
        "count": len(docs),
        "groups": groups,
        "docs": docs,
    }
    if not available:
        out["reason"] = (f"No docs directory at {DOCS_DIR}. Set HIVE_DOCS_DIR to "
                         f"point at one, or add the documents to the image.")
    return out


def get_doc(doc_id: str) -> dict[str, Any]:
    """One document, with its Markdown for the browser to render.

    Raises :class:`KeyError` for an unknown id -- the same 404 a traversal
    attempt gets, because they are the same thing from the caller's side.
    """
    entry = _resolve(doc_id)
    st = os.stat(entry["path"])
    markdown, truncated = _safe_read(entry["path"])
    return {
        "id": entry["id"],
        "file": entry["file"],
        "title": _first_heading(entry["path"]) or entry["title"],
        "group": entry["group"],
        "bytes": st.st_size,
        "mtime": _iso(st.st_mtime),
        "lines": markdown.count("\n") + 1,
        "truncated": truncated,
        "markdown": markdown,
    }
