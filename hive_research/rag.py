"""RAG engine with vector search, BM25 keyword search, and hybrid fusion."""

from __future__ import annotations

import json
import logging
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

from .config import Config
from .graph import KnowledgeGraph
from .llm import LLMInterface

logger = logging.getLogger(__name__)

# BM25 parameters
BM25_K1 = 1.5
BM25_B = 0.75
RRF_K = 60  # Reciprocal Rank Fusion constant


def _tokenize(text: str) -> list[str]:
    """Lowercase, split on non-alphanumeric, remove short tokens."""
    tokens = re.findall(r"[a-z0-9]{2,}", text.lower())
    return tokens


class BM25Index:
    """In-memory BM25 index over a collection of documents (chunks)."""

    def __init__(self) -> None:
        self._doc_count = 0
        self._avg_doc_len = 0.0
        self._doc_lens: list[int] = []
        self._df: dict[str, int] = {}  # document frequency per term
        self._tf: list[dict[str, int]] = []  # term frequency per document
        self._idf: dict[str, float] = {}

    def build(self, texts: list[str]) -> None:
        self._doc_count = len(texts)
        self._doc_lens = []
        self._df.clear()
        self._tf = []
        total_words = 0

        for text in texts:
            tokens = _tokenize(text)
            self._doc_lens.append(len(tokens))
            total_words += len(tokens)
            counter = Counter(tokens)
            self._tf.append(dict(counter))
            for term in set(tokens):
                self._df[term] = self._df.get(term, 0) + 1

        self._avg_doc_len = total_words / max(self._doc_count, 1)

        # Pre-compute IDF
        for term, df in self._df.items():
            self._idf[term] = math.log(
                (self._doc_count - df + 0.5) / (df + 0.5) + 1.0
            )

    def add_documents(self, texts: list[str]) -> None:
        """Incrementally add new documents to an existing index."""
        if self._doc_count == 0:
            self.build(texts)
            return
        new_count = len(texts)
        total_words = sum(self._doc_lens)
        for text in texts:
            tokens = _tokenize(text)
            self._doc_lens.append(len(tokens))
            total_words += len(tokens)
            counter = Counter(tokens)
            self._tf.append(dict(counter))
            for term in set(tokens):
                self._df[term] = self._df.get(term, 0) + 1
        self._doc_count += new_count
        self._avg_doc_len = total_words / max(self._doc_count, 1)
        # Recompute IDF
        for term, df in self._df.items():
            self._idf[term] = math.log(
                (self._doc_count - df + 0.5) / (df + 0.5) + 1.0
            )

    def score(self, query: str, doc_idx: int) -> float:
        """BM25 score for a single (query, document) pair."""
        tokens = _tokenize(query)
        if not tokens or doc_idx >= self._doc_count:
            return 0.0
        doc_len = self._doc_lens[doc_idx]
        tf = self._tf[doc_idx]
        score = 0.0
        for term in tokens:
            if term not in self._idf:
                continue
            idf = self._idf[term]
            term_freq = tf.get(term, 0)
            numerator = term_freq * (BM25_K1 + 1)
            denominator = term_freq + BM25_K1 * (
                1 - BM25_B + BM25_B * doc_len / self._avg_doc_len
            )
            score += idf * numerator / denominator
        return score

    def search(self, query: str, top_k: int = 10) -> list[tuple[int, float]]:
        """Return list of (doc_idx, score) sorted by BM25 score descending."""
        scores = []
        for i in range(self._doc_count):
            s = self.score(query, i)
            if s > 0:
                scores.append((i, s))
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]


class Chunk:
    def __init__(
        self,
        text: str,
        source_id: str,
        source_title: str = "",
        chunk_idx: int = 0,
    ) -> None:
        self.text = text
        self.source_id = source_id
        self.source_title = source_title
        self.chunk_idx = chunk_idx


class RAGEngine:
    def __init__(
        self,
        config: Config,
        llm: LLMInterface,
        kg: KnowledgeGraph,
    ) -> None:
        self.config = config
        self.llm = llm
        self.kg = kg
        self.store_dir = Path(config.root_dir) / "rag"
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.chunks: list[Chunk] = []
        self.embeddings: np.ndarray | None = None
        self.bm25 = BM25Index()
        self._load()

    def _index_path(self) -> Path:
        return self.store_dir / "index.json"

    def _embeddings_path(self) -> Path:
        return self.store_dir / "embeddings.npy"

    def _save(self) -> None:
        index = [
            {
                "text": c.text,
                "source_id": c.source_id,
                "source_title": c.source_title,
                "chunk_idx": c.chunk_idx,
            }
            for c in self.chunks
        ]
        with open(self._index_path(), "w") as f:
            json.dump(index, f, indent=2)
        if self.embeddings is not None:
            np.save(str(self._embeddings_path()), self.embeddings)

    def _load(self) -> None:
        if self._index_path().exists():
            try:
                with open(self._index_path()) as f:
                    index = json.load(f)
                self.chunks = [Chunk(**item) for item in index]
                if self._embeddings_path().exists():
                    self.embeddings = np.load(str(self._embeddings_path()))
                self.bm25.build([c.text for c in self.chunks])
                logger.info(
                    "Loaded RAG index with %d chunks, BM25 ready",
                    len(self.chunks),
                )
            except Exception as e:
                logger.warning("Failed to load RAG index: %s", e)

    def _chunk_text(self, text: str) -> list[str]:
        size = self.config.rag_chunk_size
        overlap = self.config.rag_chunk_overlap
        words = text.split()
        chunks = []
        start = 0
        while start < len(words):
            end = min(start + size, len(words))
            chunks.append(" ".join(words[start:end]))
            if end == len(words):
                break
            start += size - overlap
        return chunks

    def index_paper(self, paper_id: str, text: str) -> int:
        node = self.kg.get_paper(paper_id)
        title = node.label if node else paper_id
        chunks = self._chunk_text(text)
        new_chunks = []
        for i, chunk_text in enumerate(chunks):
            new_chunks.append(Chunk(chunk_text, paper_id, title, i))
        if not new_chunks:
            return 0
        new_texts = [c.text for c in new_chunks]
        new_embs = self.llm.embed_parallel(new_texts)
        new_matrix = np.array(new_embs, dtype=np.float32)
        self.chunks.extend(new_chunks)
        self.bm25.add_documents(new_texts)
        if self.embeddings is None:
            self.embeddings = new_matrix
        else:
            self.embeddings = np.vstack([self.embeddings, new_matrix])
        self._save()
        return len(new_chunks)

    def search_vector(
        self, query: str, top_k: int | None = None
    ) -> list[dict[str, Any]]:
        """Semantic vector search via cosine similarity."""
        if not self.chunks or self.embeddings is None:
            return []
        top_k = top_k or self.config.rag_top_k
        q_emb = np.array(self.llm.embed(query), dtype=np.float32)
        sims = self.embeddings @ q_emb
        norms = np.linalg.norm(self.embeddings, axis=1) * np.linalg.norm(q_emb)
        sims = np.divide(sims, norms, out=np.zeros_like(sims), where=norms != 0)
        top_indices = np.argsort(sims)[-top_k:][::-1]
        results = []
        for idx in top_indices:
            if sims[idx] > 0:
                results.append(self._format_result(idx, sims[idx]))
        return results

    def search_keyword(
        self, query: str, top_k: int | None = None
    ) -> list[dict[str, Any]]:
        """Keyword search via BM25."""
        if not self.chunks:
            return []
        top_k = top_k or self.config.rag_top_k
        bm25_results = self.bm25.search(query, top_k=top_k * 2)
        results = []
        for idx, score in bm25_results:
            results.append(self._format_result(idx, score))
        return results[:top_k]

    def search_hybrid(
        self, query: str, top_k: int | None = None, rrf_k: int = RRF_K
    ) -> list[dict[str, Any]]:
        """Hybrid search: Reciprocal Rank Fusion of vector + keyword results."""
        top_k = top_k or self.config.rag_top_k

        vec_results = self.search_vector(query, top_k=top_k * 2)
        kw_results = self.search_keyword(query, top_k=top_k * 2)

        # Build RRF score map
        rrf_scores: dict[int, float] = {}
        for rank, r in enumerate(vec_results):
            rrf_scores[r["idx"]] = rrf_scores.get(r["idx"], 0) + 1.0 / (rrf_k + rank)
        for rank, r in enumerate(kw_results):
            rrf_scores[r["idx"]] = rrf_scores.get(r["idx"], 0) + 1.0 / (rrf_k + rank)

        # Sort by RRF score
        ranked = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
        results = []
        for idx, score in ranked[:top_k]:
            results.append(self._format_result(idx, score))
        return results

    def search(
        self,
        query: str,
        top_k: int | None = None,
        mode: str = "hybrid",
    ) -> list[dict[str, Any]]:
        """Unified search interface.

        Args:
            query: The search query.
            top_k: Number of results to return.
            mode: "vector" (semantic), "keyword" (BM25), or "hybrid" (RRF fusion).

        Returns:
            List of result dicts with text, source_id, source_title, score.
        """
        if mode == "keyword":
            return self.search_keyword(query, top_k)
        elif mode == "hybrid":
            return self.search_hybrid(query, top_k)
        return self.search_vector(query, top_k)

    def _format_result(self, idx: int, score: float) -> dict[str, Any]:
        return {
            "idx": idx,
            "text": self.chunks[idx].text,
            "source_id": self.chunks[idx].source_id,
            "source_title": self.chunks[idx].source_title,
            "score": float(round(score, 4)),
        }

    def answer(
        self, query: str, mode: str = "hybrid"
    ) -> dict[str, Any]:
        """Answer a question using the specified search mode."""
        results = self.search(query, mode=mode)
        if not results:
            return {"answer": "No relevant papers found in the index.", "sources": []}
        context = "\n\n".join(
            f"[{i+1}] {r['text']}" for i, r in enumerate(results)
        )
        prompt = (
            f"Answer the question using only the provided context. "
            f"Cite sources as [1], [2], etc.\n\n"
            f"Context:\n{context}\n\n"
            f"Question: {query}\n\n"
            f"Answer:"
        )
        answer = self.llm.generate(prompt, temperature=0.0)
        sources = []
        seen = set()
        for r in results:
            if r["source_id"] not in seen:
                sources.append({
                    "id": r["source_id"],
                    "title": r["source_title"],
                })
                seen.add(r["source_id"])
        return {"answer": answer, "sources": sources}

    def stats(self) -> dict[str, Any]:
        return {
            "chunks": len(self.chunks),
            "dimension": self.embeddings.shape[1] if self.embeddings is not None else 0,
            "papers": len(set(c.source_id for c in self.chunks)),
        }
