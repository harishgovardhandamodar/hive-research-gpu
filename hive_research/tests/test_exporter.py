"""Tests for the export module.

Uses the mock knowledge graph from conftest.py.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from hive_research.exporter import (
    to_bibtex,
    to_json_dump,
    papers_to_csv,
    create_backup,
    _sanitize_bibtex,
)

from .conftest import MockKnowledgeGraph, populated_kg, mock_kg  # noqa: F401


class TestSanitizeBibtex:
    def test_escapes_special_chars(self) -> None:
        result = _sanitize_bibtex("Transformers {&} Beyond")
        assert "\\{" in result
        assert "\\}" in result
        assert "\\&" in result

    def test_preserves_normal_text(self) -> None:
        assert _sanitize_bibtex("Hello World") == "Hello World"

    def test_multiple_special(self) -> None:
        result = _sanitize_bibtex("A & B {C} $10_")
        assert "\\&" in result
        assert "\\{" in result
        assert "\\$" in result
        assert "\\_" in result


class TestToBibtex:
    def test_empty_graph(self, mock_kg: MockKnowledgeGraph) -> None:  # noqa: F811
        bibtex = to_bibtex(mock_kg)
        assert bibtex.strip() == ""

    def test_populated_graph(self, populated_kg: MockKnowledgeGraph) -> None:  # noqa: F811
        bibtex = to_bibtex(populated_kg)
        # Should have 3 entries
        assert bibtex.count("@misc{") == 3
        assert "arXiv" in bibtex
        assert "Attention Is All You Need" in bibtex

    def test_write_to_file(self, populated_kg: MockKnowledgeGraph) -> None:  # noqa: F811
        with tempfile.NamedTemporaryFile(suffix=".bib", mode="w", delete=False) as f:
            to_bibtex(populated_kg, output_path=f.name)
            content = Path(f.name).read_text()
            assert content.count("@misc{") == 3


class TestToJsonDump:
    def test_empty_graph(self, mock_kg: MockKnowledgeGraph) -> None:  # noqa: F811
        data = json.loads(to_json_dump(mock_kg))
        assert "nodes" in data
        assert "links" in data
        assert len(data["nodes"]) == 0

    def test_populated_graph(self, populated_kg: MockKnowledgeGraph) -> None:  # noqa: F811
        data = json.loads(to_json_dump(populated_kg))
        assert len(data["nodes"]) == 6  # 3 papers + 3 concepts
        assert len(data["links"]) == 6

    def test_nodes_have_labels(self, populated_kg: MockKnowledgeGraph) -> None:  # noqa: F811
        data = json.loads(to_json_dump(populated_kg))
        for node in data["nodes"]:
            assert "label" in node


class TestPapersToCsv:
    def test_empty_graph(self, mock_kg: MockKnowledgeGraph) -> None:  # noqa: F811
        csv = papers_to_csv(mock_kg)
        assert "id,title,authors,published,abstract" in csv

    def test_populated_graph(self, populated_kg: MockKnowledgeGraph) -> None:  # noqa: F811
        csv = papers_to_csv(populated_kg)
        lines = csv.strip().split("\n")
        assert len(lines) == 4  # header + 3 papers
        assert "Attention Is All You Need" in csv


class TestCreateBackup:
    def test_backup_creates_zip(self, populated_kg: MockKnowledgeGraph) -> None:  # noqa: F811
        with tempfile.TemporaryDirectory() as tmp:
            # Create dummy graph file for backup
            graph_dir = Path(tmp) / "graph"
            graph_dir.mkdir(parents=True)
            (graph_dir / "main.json").write_text('{"nodes":[],"links":[]}')

            # Create minimal config mock
            from unittest.mock import MagicMock
            config = MagicMock()
            config.root_dir = tmp
            config.graph_dir = str(graph_dir)

            zip_path = create_backup(config, output_path=Path(tmp) / "test_backup.zip", include_pdfs=False)
            assert Path(zip_path).exists()
            assert Path(zip_path).stat().st_size > 0
