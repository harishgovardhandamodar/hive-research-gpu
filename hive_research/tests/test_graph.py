"""Tests for the knowledge graph module using mocks."""

from __future__ import annotations

from .conftest import MockKnowledgeGraph, populated_kg, mock_kg  # noqa: F401


class TestMockKnowledgeGraph:
    def test_add_paper(self) -> None:
        kg = MockKnowledgeGraph()
        n = kg.add_paper("test_id", title="Test Paper", authors="Author")
        assert n.id == "test_id"
        assert n.label == "Test Paper"
        assert n.authors == "Author"

    def test_add_concept(self) -> None:
        kg = MockKnowledgeGraph()
        n = kg.add_concept("concept_1", label="Test Concept")
        assert n.id == "concept_1"
        assert n.label == "Test Concept"

    def test_get_paper_exists(self) -> None:
        kg = MockKnowledgeGraph()
        kg.add_paper("paper_1")
        assert kg.get_paper("paper_1") is not None

    def test_get_paper_missing(self) -> None:
        kg = MockKnowledgeGraph()
        assert kg.get_paper("nonexistent") is None

    def test_add_edge(self) -> None:
        kg = MockKnowledgeGraph()
        kg.add_paper("p1")
        kg.add_concept("c1")
        e = kg.add_edge("p1", "c1", "related_to")
        assert e.source == "p1"
        assert e.target == "c1"
        assert e.relation == "related_to"
        assert len(kg.edges) == 1

    def test_papers_property(self) -> None:
        kg = MockKnowledgeGraph()
        kg.add_paper("p1")
        kg.add_concept("c1")
        # Only papers should be returned (nodes with 'authors' attribute)
        assert len(kg.papers) == 1

    def test_populated_graph(self, populated_kg: MockKnowledgeGraph) -> None:  # noqa: F811
        assert len(populated_kg.papers) == 3
        assert len(populated_kg.edges) == 6
        assert populated_kg.get_paper("paper_a") is not None

    def test_edges_between_nodes(self, populated_kg: MockKnowledgeGraph) -> None:  # noqa: F811
        edges = [e for e in populated_kg.edges if e.source == "paper_a" and e.target == "transformer"]
        assert len(edges) == 1
        assert edges[0].relation == "introduces"

    def test_duplicate_paper(self) -> None:
        kg = MockKnowledgeGraph()
        kg.add_paper("p1", title="First")
        kg.add_paper("p1", title="Second")
        # get_paper returns the last added (the mock overwrites)
        assert kg.get_paper("p1").label == "Second"

    def test_no_edges_after_init(self, mock_kg: MockKnowledgeGraph) -> None:  # noqa: F811
        assert len(mock_kg.edges) == 0
        assert len(mock_kg.nodes) == 0

    def test_save_does_not_raise(self) -> None:
        kg = MockKnowledgeGraph()
        kg.save()  # Should not raise
