"""Tests for the similarity module."""

from __future__ import annotations

from hive_research.similarity import (
    ALGORITHMS,
    _author_score,
    _abstract_score,
    _concept_score_prebuilt,
    _edge_score_prebuilt,
    _build_lookups,
    _vector_score,
    jaccard_tokens,
    paper_similarity_matrix,
)

from .conftest import MockNode, MockKnowledgeGraph, populated_kg, mock_kg  # noqa: F401


class TestJaccardTokens:
    def test_identical_strings(self) -> None:
        assert jaccard_tokens("hello world", "hello world") == 1.0

    def test_disjoint_strings(self) -> None:
        assert jaccard_tokens("hello world", "foo bar") == 0.0

    def test_partial_overlap(self) -> None:
        score = jaccard_tokens("attention mechanism", "attention model")
        assert 0.0 < score < 1.0

    def test_empty_input(self) -> None:
        assert jaccard_tokens("", "hello world") == 0.0
        assert jaccard_tokens("hello world", "") == 0.0
        assert jaccard_tokens("", "") == 0.0

    def test_case_insensitive(self) -> None:
        assert jaccard_tokens("Hello World", "hello world") == 1.0


class TestAuthorScore:
    def test_same_authors(self) -> None:
        p1 = MockNode("id1", authors="John Smith, Jane Doe")
        p2 = MockNode("id2", authors="John Smith, Jane Doe")
        assert _author_score(p1, p2) == 1.0

    def test_no_overlap(self) -> None:
        p1 = MockNode("id1", authors="John Smith")
        p2 = MockNode("id2", authors="Alice Brown")
        assert _author_score(p1, p2) == 0.0

    def test_partial_overlap(self) -> None:
        p1 = MockNode("id1", authors="John Smith, Jane Doe")
        p2 = MockNode("id2", authors="John Smith, Alice Brown")
        assert _author_score(p1, p2) == 1.0 / 3.0

    def test_empty_authors(self) -> None:
        p1 = MockNode("id1", authors="")
        p2 = MockNode("id2", authors="John Smith")
        assert _author_score(p1, p2) == 0.0
        assert _author_score(p1, p1) == 0.0


class TestAbstractScore:
    def test_identical(self) -> None:
        p1 = MockNode("id1", abstract="The transformer architecture is a novel model.")
        p2 = MockNode("id2", abstract="The transformer architecture is a novel model.")
        assert _abstract_score(p1, p2) == 1.0

    def test_disjoint(self) -> None:
        p1 = MockNode("id1", abstract="Quantum physics enables secure communication.")
        p2 = MockNode("id2", abstract="The new model achieves state of the art results.")
        assert _abstract_score(p1, p2) == 0.0

    def test_empty_abstract(self) -> None:
        p1 = MockNode("id1", abstract="")
        p2 = MockNode("id2", abstract="Some abstract")
        assert _abstract_score(p1, p2) == 0.0


class TestEdgeScorePrebuilt:
    def test_edge_exists(self) -> None:
        edge_pairs = frozenset([frozenset(["a", "b"]), frozenset(["c", "d"])])
        score = _edge_score_prebuilt("a", "b", edge_pairs)
        assert score > 0.0
        assert score <= 1.0

    def test_no_edge(self) -> None:
        edge_pairs = frozenset([frozenset(["a", "b"])])
        assert _edge_score_prebuilt("a", "c", edge_pairs) == 0.0

    def test_different_order(self) -> None:
        edge_pairs = frozenset([frozenset(["a", "b"])])
        score = _edge_score_prebuilt("b", "a", edge_pairs)
        assert score > 0.0  # frozenset is unordered


class TestConceptScorePrebuilt:
    def test_shared_concept(self) -> None:
        concept_map = {
            "a": {"transformer", "nlp"},
            "b": {"transformer", "vision"},
        }
        score = _concept_score_prebuilt("a", "b", concept_map)
        assert 0.0 < score < 1.0

    def test_no_shared(self) -> None:
        concept_map = {
            "a": {"nlp"},
            "b": {"vision"},
        }
        assert _concept_score_prebuilt("a", "b", concept_map) == 0.0

    def test_missing_paper(self) -> None:
        concept_map = {"a": {"nlp"}}
        assert _concept_score_prebuilt("a", "missing", concept_map) == 0.0
        assert _concept_score_prebuilt("missing", "a", concept_map) == 0.0

    def test_identical_sets(self) -> None:
        concept_map = {
            "a": {"transformer", "nlp"},
            "b": {"transformer", "nlp"},
        }
        assert _concept_score_prebuilt("a", "b", concept_map) == 1.0


class TestVectorScore:
    def test_identical(self) -> None:
        v = [1.0, 0.0, 0.0]
        assert _vector_score(v, v) == 1.0

    def test_orthogonal(self) -> None:
        assert _vector_score([1.0, 0.0], [0.0, 1.0]) == 0.0

    def test_opposite(self) -> None:
        assert _vector_score([1.0, 0.0], [-1.0, 0.0]) == -1.0

    def test_zero_vector(self) -> None:
        assert _vector_score([0.0, 0.0], [1.0, 0.0]) == 0.0
        assert _vector_score([1.0, 0.0], [0.0, 0.0]) == 0.0


class TestBuildLookups:
    def test_build_from_graph(self, populated_kg: MockKnowledgeGraph) -> None:  # noqa: F811
        edge_pairs, concept_map = _build_lookups(populated_kg)
        assert len(edge_pairs) > 0
        assert "paper_a" in concept_map
        assert "transformer" in concept_map
        assert frozenset(["paper_a", "transformer"]) in edge_pairs

    def test_empty_graph(self, mock_kg: MockKnowledgeGraph) -> None:  # noqa: F811
        edge_pairs, concept_map = _build_lookups(mock_kg)
        assert len(edge_pairs) == 0
        assert len(concept_map) == 0


class TestPaperSimilarityMatrix:
    def test_empty_graph(self, mock_kg: MockKnowledgeGraph) -> None:  # noqa: F811
        result = paper_similarity_matrix(mock_kg, algorithm="abstract")
        assert result == []

    def test_abstract_algorithm(self, populated_kg: MockKnowledgeGraph) -> None:  # noqa: F811
        result = paper_similarity_matrix(populated_kg, algorithm="abstract")
        assert len(result) == 3  # 3 choose 2
        for entry in result:
            assert "source" in entry
            assert "target" in entry
            assert "score" in entry
            assert 0.0 <= entry["score"] <= 1.0

    def test_author_algorithm(self, populated_kg: MockKnowledgeGraph) -> None:  # noqa: F811
        result = paper_similarity_matrix(populated_kg, algorithm="author")
        assert len(result) == 3

    def test_concept_algorithm(self, populated_kg: MockKnowledgeGraph) -> None:  # noqa: F811
        result = paper_similarity_matrix(populated_kg, algorithm="concept")
        assert len(result) == 3
        # paper_a and paper_b share "transformer" concept
        entry = next(r for r in result if r["source"] == "paper_a" and r["target"] == "paper_b")
        assert entry["score"] > 0.0

    def test_combined_algorithm(self, populated_kg: MockKnowledgeGraph) -> None:  # noqa: F811
        result = paper_similarity_matrix(populated_kg, algorithm="combined")
        assert len(result) == 3
        # Results should be sorted by score descending
        scores = [r["score"] for r in result]
        assert scores == sorted(scores, reverse=True)

    def test_top_k(self, populated_kg: MockKnowledgeGraph) -> None:  # noqa: F811
        result = paper_similarity_matrix(populated_kg, algorithm="abstract", top_k=1)
        assert len(result) == 1

    def test_paper_ids_filter(self, populated_kg: MockKnowledgeGraph) -> None:  # noqa: F811
        result = paper_similarity_matrix(
            populated_kg, paper_ids=["paper_a", "paper_b"], algorithm="abstract"
        )
        assert len(result) == 1
        assert result[0]["source"] == "paper_a"
        assert result[0]["target"] == "paper_b"

    def test_invalid_algorithm(self, populated_kg: MockKnowledgeGraph) -> None:  # noqa: F811
        result = paper_similarity_matrix(populated_kg, algorithm="nonexistent")
        # Falls back to "combined"
        assert len(result) == 3

    def test_author_overlap_included(self, populated_kg: MockKnowledgeGraph) -> None:  # noqa: F811
        result = paper_similarity_matrix(populated_kg, algorithm="abstract")
        for entry in result:
            assert "author_overlap" in entry
            assert "abstract_sim" in entry


class TestAlgorithms:
    def test_all_algorithms_have_labels(self) -> None:
        for name, algo in ALGORITHMS.items():
            assert "label" in algo, f"{name} missing label"
            assert "desc" in algo, f"{name} missing desc"
            assert callable(algo["fn"]), f"{name} fn is not callable"
