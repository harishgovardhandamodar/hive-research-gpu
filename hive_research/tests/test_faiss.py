"""Tests for FAISS integration in the RAG engine."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest

from hive_research.rag import RAGEngine, Chunk


def test_faiss_not_available_by_default() -> None:
    """FAISS is optional — engine falls back to numpy."""
    config = MagicMock()
    config.root_dir = "/tmp/test_faiss"
    config.rag_top_k = 3
    llm = MagicMock()
    llm.embed.return_value = [0.1] * 4
    kg = MagicMock()
    engine = RAGEngine(config, llm, kg)

    assert engine._faiss_index is None

    # Add some chunks
    engine.chunks = [
        Chunk("test document one", "paper_1", "Paper 1", 0),
        Chunk("test document two", "paper_2", "Paper 2", 0),
    ]
    engine.embeddings = np.array([[0.1, 0.2, 0.3, 0.4],
                                  [0.5, 0.6, 0.7, 0.8]], dtype=np.float32)

    # FAISS _build_faiss checks _HAVE_FAISS — safe to call without faiss
    engine._build_faiss()
    assert engine._faiss_index is None  # not available

    # Falls back to numpy search
    results = engine.search_vector("test", top_k=2)
    assert len(results) <= 2


def test_faiss_search_matches_numpy() -> None:
    """Both code paths should return similar results."""
    from unittest.mock import MagicMock, patch

    config = MagicMock()
    config.root_dir = "/tmp/test_faiss_match"
    config.rag_top_k = 3

    llm = MagicMock()
    llm.embed.return_value = [1.0, 0.0, 0.0, 0.0]

    kg = MagicMock()
    engine = RAGEngine(config, llm, kg)

    # Add chunks with known embeddings
    engine.chunks = [
        Chunk("first doc about transformers", "p1", "Paper 1", 0),
        Chunk("second doc about vision", "p2", "Paper 2", 0),
        Chunk("third doc about everything", "p3", "Paper 3", 0),
    ]
    engine.embeddings = np.array([
        [1.0, 0.0, 0.0, 0.0],  # closest to query
        [0.0, 1.0, 0.0, 0.0],
        [0.5, 0.5, 0.0, 0.0],
    ], dtype=np.float32)

    # Mock _HAVE_FAISS to True
    with patch("hive_research.rag._HAVE_FAISS", True):
        with patch("hive_research.rag.faiss") as mock_faiss:
            mock_index = MagicMock()
            mock_index.search.return_value = (
                np.array([[1.0, 0.7, 0.5]]),
                np.array([[0, 2, 1]]),
            )
            mock_faiss.IndexFlatIP.return_value = mock_index
            mock_faiss.__bool__.return_value = True

            engine._faiss_index = mock_index
            results = engine.search_vector("transformers", top_k=2)
            assert len(results) >= 1
            # First result should be index 0 (closest)
            assert results[0]["source_id"] == "p1"
