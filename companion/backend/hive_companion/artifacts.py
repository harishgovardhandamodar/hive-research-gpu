"""Artifact discovery: files the agent's work produced in the hive vault.

Surveys, digests and paper notes live in the vault; the main server's
/api/browse exposes them. This module reshapes that tree into GUI-friendly
groups where every file carries the path needed to read it back through
/api/read. Only text-renderable files are offered — the inline viewer is
markdown-based, so binaries (figures, PDFs) are excluded.
"""

from __future__ import annotations

import os
from typing import Any

GROUP_SPECS = [
    ("reports", "Survey reports"),
    ("digests", "Digests"),
    ("notes", "Paper notes"),
]

TEXT_EXTS = {".md", ".txt"}
MAX_NOTES_FILES = 80


def _readable(name: str) -> bool:


    base = os.path.basename(name)
    if base.startswith(".") or base.endswith(".bak"):
        return False
    return os.path.splitext(base)[1].lower() in TEXT_EXTS


def shape_artifacts(tree: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, dict[str, Any]] = {
        gid: {"id": gid, "label": label, "files": [], "total": 0} for gid, label in GROUP_SPECS
    }

    for entry in tree:
        if entry.get("name") != "Notes":
            continue  # source PDFs are inputs, not agent artifacts
        for sub in entry.get("files", []):
            sub_name = sub.get("name", "")
            files = [f for f in sub.get("files", []) if _readable(f.get("name", ""))]
            if sub_name in groups:
                groups[sub_name]["files"].extend(
                    {
                        "name": f["name"],
                        "path": f"Notes/{sub_name}/{f['name']}",
                        **({"mtime": f["mtime"]} if f.get("mtime") else {}),
                    }
                    for f in files
                )
            else:  # paper-note folder
                for f in files:
                    entry = {"name": f"{sub_name}/{f['name']}", "path": f"Notes/{sub_name}/{f['name']}"}
                    if f.get("mtime"):
                        entry["mtime"] = f["mtime"]
                    groups["notes"]["files"].append(entry)

    for gid, _ in GROUP_SPECS:
        groups[gid]["total"] = len(groups[gid]["files"])
    groups["notes"]["files"] = sorted(groups["notes"]["files"], key=lambda f: f["name"])[:MAX_NOTES_FILES]
    return {"groups": [groups[gid] for gid, _ in GROUP_SPECS]}


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}
VIEWABLE_TEXT_EXTS = {".md", ".txt"}
PDF_EXTS = {".pdf"}


def _build_dir(name: str, rel_files: list[dict[str, Any]], folder_prefix: str) -> dict[str, Any]:
    """Nest flat relative paths ('figures/x.png', 'notes.md') into a dir node."""
    node: dict[str, Any] = {"name": name, "type": "dir", "children": []}
    index = node["children"]
    ordered = sorted(rel_files, key=lambda f: f["name"])
    for item in ordered:
        rel = item["name"]
        parts = [p for p in rel.split("/") if p]
        cursor = index
        for i, part in enumerate(parts):
            last = i == len(parts) - 1
            existing = next((c for c in cursor if c["name"] == part and c["type"] == ("file" if last else "dir")), None)
            if existing:
                cursor = existing.setdefault("children", [])
                continue
            child: dict[str, Any] = {"name": part, "type": "file" if last else "dir"}
            if last:
                ext = os.path.splitext(part)[1].lower()
                child["ext"] = ext
                if ext in VIEWABLE_TEXT_EXTS:
                    child["view"] = "text"
                elif ext in IMAGE_EXTS:
                    child["view"] = "image"
                elif ext in PDF_EXTS:
                    child["view"] = "pdf"
                else:
                    child["view"] = "none"
                child["path"] = f"{folder_prefix}/{rel}"
                if item.get("mtime"):
                    child["mtime"] = item["mtime"]
                cursor.append(child)
            else:
                child["children"] = []
                cursor.append(child)
                cursor = child["children"]
    return node


def build_explorer(tree: list[dict[str, Any]]) -> dict[str, Any]:
    """Full vault hierarchy for the GUI file explorer (figures + source PDFs)."""
    notes = next((e for e in tree if e.get("name") == "Notes"), None)
    children: list[dict[str, Any]] = []
    source_pdfs = _build_dir(
        "source-pdfs",
        [e for e in tree if isinstance(e, dict) and str(e.get("name", "")).lower().endswith(".pdf")],
        "",
    )
    if source_pdfs.get("children"):
        children.append(source_pdfs)
    if notes:
        for sub in notes.get("files", []):
            sub_name = sub.get("name", "")
            files = [
                f
                for f in sub.get("files", [])
                if not os.path.basename(f["name"]).startswith(".") and not f["name"].endswith(".bak")
            ]
            children.append(_build_dir(sub_name, files, f"Notes/{sub_name}"))
        children.sort(key=lambda c: (c["type"] != "dir", c["name"].lower()))
    return {"name": "vault", "type": "dir", "children": children}
