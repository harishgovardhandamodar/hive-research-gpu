"""Artifact discovery: files the agent's work produced in the hive vault.

Surveys, digests and paper notes live in the vault; the main server's
/api/browse exposes them. This module reshapes that tree into GUI-friendly
groups where every file carries the path needed to read it back through
/api/read. Only text-renderable files are offered — the inline viewer is
markdown-based, so binaries (figures, PDFs) are excluded.
"""

from __future__ import annotations

from typing import Any

GROUP_SPECS = [
    ("surveys", "Survey reports"),
    ("digests", "Digests"),
    ("notes", "Paper notes"),
]

TEXT_EXTS = {".md", ".txt"}
MAX_NOTES_FILES = 80


def _readable(name: str) -> bool:
    import os

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
                    {"name": f["name"], "path": f"Notes/{sub_name}/{f['name']}"} for f in files
                )
            else:  # paper-note folder
                for f in files:
                    groups["notes"]["files"].append(
                        {"name": f"{sub_name}/{f['name']}", "path": f"Notes/{sub_name}/{f['name']}"}
                    )

    for gid, _ in GROUP_SPECS:
        groups[gid]["total"] = len(groups[gid]["files"])
    groups["notes"]["files"] = sorted(groups["notes"]["files"], key=lambda f: f["name"])[:MAX_NOTES_FILES]
    return {"groups": [groups[gid] for gid, _ in GROUP_SPECS]}
