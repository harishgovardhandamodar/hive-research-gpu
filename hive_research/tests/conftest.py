"""Shared fixtures and mock objects for hive-research-gpu tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest


class MockNode:
    """Minimal node mock that emulates KnowledgeGraph paper/concept nodes."""
    def __init__(
        self,
        node_id: str,
        label: str = "",
        authors: str = "",
        published: str = "",
        abstract: str = "",
        **kwargs: Any,
    ) -> None:
        self.id = node_id
        self.label = label or node_id
        self.authors = authors
        self.published = published
        self.abstract = abstract
        for k, v in kwargs.items():
            setattr(self, k, v)


class MockEdge:
    """Minimal edge mock."""
    def __init__(self, source: str, target: str, relation: str = "related_to") -> None:
        self.source = source
        self.target = target
        self.relation = relation


class MockKnowledgeGraph:
    """In-memory mock of KnowledgeGraph for unit testing."""

    def __init__(self) -> None:
        self._nodes: dict[str, MockNode] = {}
        self._edges: list[MockEdge] = []

    def add_paper(
        self,
        paper_id: str,
        title: str = "",
        authors: str = "",
        published: str = "",
        abstract: str = "",
        **kwargs: Any,
    ) -> MockNode:
        n = MockNode(paper_id, title, authors, published, abstract, **kwargs)
        self._nodes[paper_id] = n
        return n

    def add_concept(
        self, concept_id: str, label: str = "", **kwargs: Any
    ) -> MockNode:
        n = MockNode(concept_id, label or concept_id, **kwargs)
        self._nodes[concept_id] = n
        return n

    def get_paper(self, paper_id: str) -> MockNode | None:
        return self._nodes.get(paper_id)

    def add_edge(self, source: str, target: str, relation: str = "related_to") -> MockEdge:
        e = MockEdge(source, target, relation)
        self._edges.append(e)
        return e

    @property
    def papers(self) -> list[MockNode]:
        return [n for n in self._nodes.values() if hasattr(n, 'authors')]

    @property
    def nodes(self) -> list[MockNode]:
        return list(self._nodes.values())

    @property
    def edges(self) -> list[MockEdge]:
        return self._edges

    def save(self) -> None:
        pass


@pytest.fixture
def mock_kg() -> MockKnowledgeGraph:
    """Returns an empty mock knowledge graph."""
    return MockKnowledgeGraph()


@pytest.fixture
def populated_kg() -> MockKnowledgeGraph:
    """Returns a knowledge graph with 3 papers and some edges."""
    kg = MockKnowledgeGraph()
    kg.add_paper("paper_a", "Attention Is All You Need",
                  authors="Vaswani et al.",
                  published="2017-06-12",
                  abstract="The dominant sequence transduction models are based on complex recurrent or convolutional neural networks that include an encoder and a decoder.")
    kg.add_paper("paper_b", "BERT: Pre-training of Deep Bidirectional Transformers",
                  authors="Devlin et al.",
                  published="2018-10-11",
                  abstract="We introduce a new language representation model called BERT, which stands for Bidirectional Encoder Representations from Transformers.")
    kg.add_paper("paper_c", "An Image is Worth 16x16 Words: Transformers for Image Recognition",
                  authors="Dosovitskiy et al.",
                  published="2020-10-22",
                  abstract="While the Transformer architecture has become the de-facto standard for natural language processing tasks.")
    kg.add_concept("transformer", "Transformer Architecture")
    kg.add_concept("nlp", "Natural Language Processing")
    kg.add_concept("vision", "Computer Vision")
    kg.add_edge("paper_a", "transformer", "introduces")
    kg.add_edge("paper_a", "nlp", "related_to")
    kg.add_edge("paper_b", "transformer", "uses")
    kg.add_edge("paper_b", "nlp", "related_to")
    kg.add_edge("paper_c", "transformer", "uses")
    kg.add_edge("paper_c", "vision", "related_to")
    return kg


@pytest.fixture
def mock_llm() -> MagicMock:
    """Returns a mock LLMInterface for pipeline tests."""
    llm = MagicMock()
    llm.extract_structured.return_value = {
        "summary": "A test summary.",
        "concepts": [{"name": "test concept", "definition": "A test concept."}],
        "tags": ["test"],
        "relations": [],
    }
    llm.generate.return_value = "A generated answer."
    llm.embed.return_value = [0.1] * 768
    llm.embed_parallel.return_value = [[0.1] * 768, [0.2] * 768]
    return llm
