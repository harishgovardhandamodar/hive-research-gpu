from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any

import numpy as np

from .config import Config
from .graph import KnowledgeGraph
from .llm import LLMInterface

logger = logging.getLogger(__name__)

# Hybrid retrieval weights: dense cosine vs lexical token overlap.
# Lexical matters for exact identifiers ("DPO", "RLHF") that embed poorly.
LEXICAL_WEIGHT = 0.35


def _tokens(text: str) -> set[str]:
    return {t for t in text.lower().split() if len(t) > 1}


class Chunk:
    def __init__(
        self,
        text: str,
        source_id: str,
        source_title: str = "",
        chunk_idx: int = 0,
        page_start: int = 0,
        page_end: int = 0,
    ) -> None:
        self.text = text
        self.source_id = source_id
        self.source_title = source_title
        self.chunk_idx = chunk_idx
        self.page_start = int(page_start or 0)
        self.page_end = int(page_end or 0)


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
        self._load()

    def _index_path(self) -> Path:
        return self.store_dir / "index.json"

    def _embeddings_path(self) -> Path:
        return self.store_dir / "embeddings.npy"

    def _meta_path(self) -> Path:
        return self.store_dir / "embeddings_meta.json"

    def _save(self) -> None:
        index = [
            {
                "text": c.text,
                "source_id": c.source_id,
                "source_title": c.source_title,
                "chunk_idx": c.chunk_idx,
                "page_start": c.page_start,
                "page_end": c.page_end,
            }
            for c in self.chunks
        ]
        with open(self._index_path(), "w") as f:
            json.dump(index, f, indent=2)
        if self.embeddings is not None:
            np.save(str(self._embeddings_path()), self.embeddings)
            meta = {
                "embed_model": self.config.ollama_embed_model,
                "dim": int(self.embeddings.shape[1]),
                "chunks": len(self.chunks),
            }
            self._meta_path().write_text(json.dumps(meta))

    def _load(self) -> None:
        if self._index_path().exists():
            try:
                with open(self._index_path()) as f:
                    index = json.load(f)
                # Tolerant load: older indexes lack page fields.
                known = {"text", "source_id", "source_title", "chunk_idx", "page_start", "page_end"}
                chunks = [Chunk(**{k: v for k, v in item.items() if k in known}) for item in index]
                embeddings = None
                if self._embeddings_path().exists():
                    embeddings = np.load(str(self._embeddings_path()))
                    # Model drift: vectors from a different embed model are a
                    # different space — mixing them silently degrades answers.
                    if self._meta_path().exists():
                        try:
                            meta = json.loads(self._meta_path().read_text())
                            stamped = meta.get("embed_model")
                        except Exception:
                            stamped = None
                        current = self.config.ollama_embed_model
                        if stamped and stamped != current:
                            logger.warning(
                                "RAG vectors were built with '%s' but config "
                                "now uses '%s' — discarding vectors; call "
                                "rebuild() to re-embed with the new model",
                                stamped, current,
                            )
                            embeddings = None
                    if len(chunks) != len(embeddings if embeddings is not None else chunks):
                        # The two files are written separately; a crash between
                        # writes leaves them out of sync. Vectors pointing at
                        # wrong chunks would silently corrupt every answer,
                        # so discard them and allow a rebuild from chunk texts.
                        logger.warning(
                            "RAG index/embeddings mismatch (%d chunks vs %d "
                            "vectors) — discarding vectors; call rebuild() "
                            "to re-embed",
                            len(chunks),
                            len(embeddings),
                        )
                        embeddings = None
                self.chunks = chunks
                self.embeddings = embeddings
                logger.info("Loaded RAG index with %d chunks", len(self.chunks))
            except Exception as e:
                logger.warning("Failed to load RAG index: %s", e)

    def rebuild(self) -> dict[str, Any]:
        """Re-embed all stored chunks (used after vector loss/corruption)."""
        if not self.chunks:
            return {"status": "empty", "chunks": 0}
        texts = [c.text for c in self.chunks]
        batch = 64
        matrices = []
        for i in range(0, len(texts), batch):
            matrices.append(np.array(self.llm.embed_parallel(texts[i:i + batch]), dtype=np.float32))
        self.embeddings = np.vstack(matrices)
        self._save()
        logger.info("RAG rebuilt: %d chunks re-embedded", len(self.chunks))
        return {"status": "ok", "chunks": len(self.chunks), "dimension": int(self.embeddings.shape[1])}

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

    def index_paper(self, paper_id: str, text: str, pages: list[dict[str, Any]] | None = None) -> int:
        """Index a paper's text.

        When ``pages`` (from parser.extract_text_pages) is given, chunks are
        built per page and carry page_start/page_end for citations. Plain
        ``text`` alone keeps the legacy whole-document chunking.
        """
        node = self.kg.get_paper(paper_id)
        title = node.label if node else paper_id
        # Drop any previous chunks for this paper so re-indexing never duplicates
        if any(c.source_id == paper_id for c in self.chunks):
            keep_indices = [i for i, c in enumerate(self.chunks) if c.source_id != paper_id]
            removed_before = len(self.chunks)
            self.chunks = [self.chunks[i] for i in keep_indices]
            if self.embeddings is not None:
                self.embeddings = self.embeddings[keep_indices]
            logger.info(
                "Re-indexing %s: replaced %d old chunks",
                paper_id,
                removed_before - len(self.chunks),
            )
        new_chunks: list[Chunk] = []
        if pages:
            idx = 0
            for p in pages:
                page_num = int(p.get("page", 0))
                for piece in self._chunk_text(p.get("text", "")):
                    new_chunks.append(Chunk(piece, paper_id, title, idx, page_num, page_num))
                    idx += 1
        else:
            for i, chunk_text in enumerate(self._chunk_text(text)):
                new_chunks.append(Chunk(chunk_text, paper_id, title, i))
        if not new_chunks:
            return 0
        new_texts = [c.text for c in new_chunks]
        new_embs = self.llm.embed_parallel(new_texts)
        new_matrix = np.array(new_embs, dtype=np.float32)
        self.chunks.extend(new_chunks)
        if self.embeddings is None:
            self.embeddings = new_matrix
        else:
            self.embeddings = np.vstack([self.embeddings, new_matrix])
        self._save()
        return len(new_chunks)

    def search(self, query: str, top_k: int | None = None) -> list[dict[str, Any]]:
        if not self.chunks or self.embeddings is None:
            return []
        if len(self.chunks) != len(self.embeddings):  # defensive: never cite wrong chunks
            logger.warning("RAG search skipped: index/vectors out of sync")
            return []
        top_k = top_k or self.config.rag_top_k
        q_emb = np.array(self.llm.embed(query), dtype=np.float32)
        sims = self.embeddings @ q_emb
        norms = np.linalg.norm(self.embeddings, axis=1) * np.linalg.norm(q_emb)
        sims = np.divide(sims, norms, out=np.zeros_like(sims), where=norms != 0)

        # Lexical blend: exact token overlap rescues acronyms/method names
        # that dense embeddings rank poorly.
        q_tokens = _tokens(query)
        chunk_tokens = [_tokens(c.text) for c in self.chunks]
        lex = np.array([
            len(q_tokens & ct) / max(len(q_tokens), 1) for ct in chunk_tokens
        ], dtype=np.float32)
        combined = (1.0 - LEXICAL_WEIGHT) * sims + LEXICAL_WEIGHT * lex

        top_indices = np.argsort(combined)[-top_k:][::-1]
        results = []
        for idx in top_indices:
            if combined[idx] > 0:
                c = self.chunks[idx]
                results.append({
                    "text": c.text,
                    "source_id": c.source_id,
                    "source_title": c.source_title,
                    "score": float(round(float(combined[idx]), 4)),
                    "dense_score": float(round(float(sims[idx]), 4)),
                    "lexical_score": float(round(float(lex[idx]), 4)),
                    "page": int(c.page_start) if c.page_start else None,
                })
        return results

    def answer(self, query: str) -> dict[str, Any]:
        results = self.search(query)
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
