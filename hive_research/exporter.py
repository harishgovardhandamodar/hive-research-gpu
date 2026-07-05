"""Export/import utilities for Hive Research GPU.

Supports BibTeX, JSON graph dump, and full backup archive.
"""

from __future__ import annotations

import json
import logging
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import Config
from .graph import KnowledgeGraph

logger = logging.getLogger(__name__)


def _sanitize_bibtex(text: str) -> str:
    """Escape special characters for BibTeX fields."""
    text = text.replace("\\", "\\\\")
    text = text.replace("{", "\\{")
    text = text.replace("}", "\\}")
    text = text.replace("$", "\\$")
    text = text.replace("&", "\\&")
    text = text.replace("#", "\\#")
    text = text.replace("%", "\\%")
    text = text.replace("_", "\\_")
    text = text.replace("^", "\\^")
    text = text.replace("~", "\\textasciitilde{}")
    return text


def to_bibtex(kg: KnowledgeGraph, output_path: str | Path | None = None) -> str:
    """Export all papers in the knowledge graph as BibTeX format.

    Args:
        kg: KnowledgeGraph instance
        output_path: Optional file path to write the BibTeX

    Returns:
        BibTeX string
    """
    entries: list[str] = []
    for paper in kg.papers:
        arxiv_id = paper.arxiv_id or paper.id
        key = arxiv_id.replace(".", "").replace("/", "")
        title = _sanitize_bibtex(paper.label or "")
        authors = _sanitize_bibtex(
            paper.authors if paper.authors else "Unknown"
        )
        year = (paper.published or "")[:4] if paper.published else "unknown"

        entry = f"@misc{{{key},\n"
        entry += f"  author = {{{authors}}},\n"
        entry += f"  title = {{{title}}},\n"
        entry += f"  year = {{{year}}},\n"
        entry += f"  eprint = {{{arxiv_id}}},\n"
        entry += f"  archivePrefix = {{arXiv}},\n"
        if paper.abstract:
            abstract = _sanitize_bibtex(paper.abstract[:500])
            entry += f"  abstract = {{{abstract}}},\n"
        entry += f"  url = {{https://arxiv.org/abs/{arxiv_id}}}\n"
        entry += "}\n"
        entries.append(entry)

    result = "\n".join(entries)
    if output_path:
        Path(output_path).write_text(result)
        logger.info("Exported %d papers to BibTeX: %s", len(entries), output_path)
    return result


def to_json_dump(kg: KnowledgeGraph, output_path: str | Path | None = None) -> str:
    """Export the full knowledge graph as a JSON dump.

    Includes all nodes and edges with metadata.

    Args:
        kg: KnowledgeGraph instance
        output_path: Optional file path to write the JSON

    Returns:
        JSON string
    """
    data = kg.to_node_link()
    result = json.dumps(data, indent=2, default=str)
    if output_path:
        Path(output_path).write_text(result)
        logger.info("Exported graph JSON dump to: %s", output_path)
    return result


def create_backup(
    config: Config,
    output_path: str | Path | None = None,
    include_pdfs: bool = True,
) -> str:
    """Create a timestamped ZIP backup of all project data.

    Args:
        config: Config instance
        output_path: Optional path for the backup ZIP
        include_pdfs: Whether to include PDF files (can be large)

    Returns:
        Path to the created backup ZIP
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if output_path is None:
        backups_dir = Path(config.root_dir) / "backups"
        backups_dir.mkdir(parents=True, exist_ok=True)
        output_path = backups_dir / f"hive_backup_{timestamp}.zip"

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # Graph data
        graph_dir = Path(config.graph_dir)
        if graph_dir.exists():
            for f in graph_dir.iterdir():
                if f.is_file():
                    zf.write(f, arcname=f"graph/{f.name}")

        # Vault notes
        vault_dir = Path(config.vault_dir)
        if vault_dir.exists():
            for f in vault_dir.rglob("*"):
                if f.is_file():
                    zf.write(f, arcname=f"vault/{f.relative_to(vault_dir)}")

        # RAG index
        rag_dir = Path(config.root_dir) / "rag"
        if rag_dir.exists():
            for f in rag_dir.iterdir():
                if f.is_file():
                    zf.write(f, arcname=f"rag/{f.name}")

        # Research pool
        pool_dir = Path(config.root_dir) / "pool"
        if pool_dir.exists():
            for f in pool_dir.rglob("*"):
                if f.is_file():
                    zf.write(f, arcname=f"pool/{f.relative_to(pool_dir)}")

        # Config
        for cfg_name in ("config.yaml", "config.local.yaml"):
            cfg_path = Path(cfg_name)
            if cfg_path.exists():
                zf.write(cfg_path, arcname=cfg_name)

        # PDFs (optional — large)
        if include_pdfs:
            papers_dir = Path(config.papers_dir)
            if papers_dir.exists():
                for f in papers_dir.iterdir():
                    if f.is_file() and f.suffix.lower() == ".pdf":
                        zf.write(f, arcname=f"papers/{f.name}")

    size_mb = output_path.stat().st_size / (1024 * 1024)
    logger.info("Backup created: %s (%.1f MB)", output_path, size_mb)
    return str(output_path)


def papers_to_csv(kg: KnowledgeGraph, output_path: str | Path | None = None) -> str:
    """Export papers as CSV for spreadsheet import.

    Fields: id, title, authors, published, abstract (first 500 chars)

    Args:
        kg: KnowledgeGraph instance
        output_path: Optional file path

    Returns:
        CSV string
    """
    import csv
    import io

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "title", "authors", "published", "abstract"])

    for paper in kg.papers:
        writer.writerow([
            paper.arxiv_id or paper.id,
            paper.label or "",
            (paper.authors or "")[:200],
            paper.published or "",
            (paper.abstract or "")[:500],
        ])

    result = buf.getvalue()
    if output_path:
        Path(output_path).write_text(result)
        logger.info("Exported CSV: %s", output_path)
    return result
