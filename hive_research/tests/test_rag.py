"""Tests for the RAG engine including BM25 and hybrid search."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest

from hive_research.rag import BM25Index, Chunk, RAGEngine, _tokenize


class TestTokenize:
    def test_basic(self) -> None:
        assert _tokenize("Attention Is All You Need") == ["attention", "all", "you", "need"]

    def test_lowercase(self) -> None:
        assert _tokenize("Hello WORLD") == ["hello", "world"]

    def test_strips_punctuation(self) -> None:
        tokens = _tokenize("graph neural networks!")
        assert "networks" in tokens

    def test_short_tokens_excluded(self) -> None:
        assert "a" not in _tokenize("a test of the system")


class TestBM25Index:
    def test_empty_index(self) -> None:
        bm25 = BM25Index()
        assert bm25.search("test") == []

    def test_single_document(self) -> None:
        bm25 = BM25Index()
        bm25.build(["the cat sat on the mat"])
        results = bm25.search("cat mat", top_k=5)
        assert len(results) == 1
        assert results[0][0] == 0
        assert results[0][1] > 0

    def test_multiple_documents(self) -> None:
        docs = [
            "machine learning is transforming artificial intelligence",
            "deep neural networks learn from data",
            "the cat sat on the mat",
        ]
        bm25 = BM25Index()
        bm25.build(docs)
        results = bm25.search("machine learning", top_k=3)
        assert len(results) >= 1
        # The first doc should be most relevant
        assert results[0][0] == 0

    def test_relevance_ranking(self) -> None:
        docs = [
            "transformers for natural language processing tasks",
            "the weather today is sunny and warm",
            "transformer architectures in deep learning for nlp",
        ]
        bm25 = BM25Index()
        bm25.build(docs)
        results = bm25.search("transformer nlp", top_k=3)
        assert len(results) == 3
        # Documents containing 'transformer' and 'nlp' should rank higher
        top_idx = results[0][0]
        assert top_idx in (0, 2)

    def test_add_documents(self) -> None:
        bm25 = BM25Index()
        bm25.build(["first document about AI"])
        bm25.add_documents(["second document about ML"])
        assert bm25._doc_count == 2
        results = bm25.search("ML", top_k=5)
        assert len(results) >= 1

    def test_score_zero_for_empty_query(self) -> None:
        bm25 = BM25Index()
        bm25.build(["some text"])
        assert bm25.score("", 0) == 0.0


class TestRAGEngine:
    @pytest.fixture
    def engine(self) -> RAGEngine:
        config = MagicMock()
        config.root_dir = "/tmp/test_rag"
        config.rag_chunk_size = 50
        config.rag_chunk_overlap = 10
        config.rag_top_k = 3

        llm = MagicMock()
        llm.embed.return_value = [0.1] * 4
        llm.embed_parallel.return_value = [[0.1] * 4, [0.2] * 4, [0.3] * 4]
        llm.generate.return_value = "A test answer."

        kg = MagicMock()
        kg.get_paper.return_value = MagicMock(label="Test Paper")

        engine = RAGEngine(config, llm, kg)
        engine.chunks = [
            Chunk("Transformers are great for NLP.", "paper_1", "Paper One", 0),
            Chunk("Machine learning is a broad field.", "paper_2", "Paper Two", 0),
            Chunk("The cat sat on the mat.", "paper_3", "Paper Three", 0),
        ]
        engine.embeddings = np.array([[0.1, 0.2, 0.3, 0.4],
                                      [0.5, 0.6, 0.7, 0.8],
                                      [0.9, 0.0, 0.1, 0.2]], dtype=np.float32)
        engine.bm25.build([c.text for c in engine.chunks])
        return engine

    def test_search_vector(self, engine: RAGEngine) -> None:
        results = engine.search_vector("machine learning", top_k=2)
        assert len(results) <= 2
        for r in results:
            assert "idx" in r
            assert "text" in r
            assert "score" in r

    def test_search_keyword(self, engine: RAGEngine) -> None:
        results = engine.search_keyword("transformers", top_k=3)
        assert len(results) >= 1

    def test_search_hybrid(self, engine: RAGEngine) -> None:
        results = engine.search_hybrid("transformers nlp", top_k=2)
        assert len(results) <= 2

    def test_search_mode_vector(self, engine: RAGEngine) -> None:
        results = engine.search("machine learning", mode="vector")
        assert len(results) > 0

    def test_search_mode_keyword(self, engine: RAGEngine) -> None:
        results = engine.search("cat mat", mode="keyword")
        assert len(results) > 0

    def test_search_mode_hybrid(self, engine: RAGEngine) -> None:
        results = engine.search("transformers", mode="hybrid")
        assert len(results) > 0

    def test_search_empty_engine(self) -> None:
        config = MagicMock()
        config.root_dir = "/tmp/test_rag"
        config.rag_top_k = 3
        engine = RAGEngine(config, MagicMock(), MagicMock())
        assert engine.search("test") == []

    def test_answer_no_results(self) -> None:
        config = MagicMock()
        config.root_dir = "/tmp/test_rag"
        engine = RAGEngine(config, MagicMock(), MagicMock())
        result = engine.answer("query")
        assert "No relevant papers" in result["answer"]

    def test_answer_with_results(self, engine: RAGEngine) -> None:
        result = engine.answer("machine learning")
        assert "answer" in result
        assert "sources" in result
        assert result["sources"]  # at least one source
