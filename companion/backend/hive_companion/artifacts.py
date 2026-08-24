"""Artifact discovery: files the agent's work produced in the hive vault.

Surveys, digests and paper notes all live in the vault; the main server's
/api/browse exposes them. This module reshapes that tree into GUI-friendly
groups where every file carries the path needed to read it back through
/api/read.
"""

from __future__ import annotations

from typing import Any

GROUP_SPECS = [
    ("surveys", "Survey reports"),
    ("digests", "Digests"),
    ("notes", "Paper notes"),
]

MAX_NOTES_FILES = 80
MAX_PAPERS_FILES = 24


def _file(name: str, rel: str, folder: str | None) -> dict[str, Any]:
    path = f"{folder}/{rel}" if folder else rel
    return {"name": rel or name, "path": f"Notes/{path}" if folder else name}


def shape_artifacts(tree: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, dict[str, Any]] = {
        gid: {"id": gid, "label": label, "files": [], "total": 0} for gid, label in GROUP_SPECS
    }
    papers: list[dict[str, Any]] = []

    for entry in tree:
        name = entry.get("name", "")
        if name == "Notes":
            for sub in entry.get("files", []):
                sub_name = sub.get("name", "")
                files = sub.get("files", [])
                if sub_name in groups:  # surveys/, digests/
                    groups[sub_name]["files"].extend(
                        {"name": f["name"], "path": f"Notes/{sub_name}/{f['name']}"} for f in files
                    )
                else:  # paper-note folder
                    for f in files:
                        groups["notes"]["files"].append(
                            {"name": f"{sub_name}/{f['name']}", "path": f"Notes/{sub_name}/{f['name']}"}
                        )
        elif name.lower().endswith(".pdf"):
            papers.append({"name": name, "path": name})

    for gid, _ in GROUP_SPECS:
        groups[gid]["total"] = len(groups[gid]["files"])
    groups["notes"]["files"] = sorted(groups["notes"]["files"], key=lambda f: f["name"])[:MAX_NOTES_FILES]
    papers_sorted = sorted(papers, key=lambda f: f["name"])
    return {
        "groups": [groups[gid] for gid, _ in GROUP_SPECS]
        + [{"id": "papers", "label": "Source PDFs", "files": papers_sorted[:MAX_PAPERS_FILES], "total": len(papers_sorted)}],
    }
