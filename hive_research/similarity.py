from __future__ import annotations

import functools
import math
from typing import Any

from .graph import KnowledgeGraph


def _build_lookups(kg: KnowledgeGraph) -> tuple[frozenset, dict[str, set[str]]]:
    """Pre-build edge set and concept map for O(1) lookups.

    Returns (edge_pairs, concept_map) where:
      - edge_pairs is a frozenset of frozensets {source, target} for fast edge membership
      - concept_map maps paper_id -> set of concept_ids linked to it
    """
    edge_pairs = set()
    concept_map: dict[str, set[str]] = {}
    for e in kg.edges:
        pair = frozenset([e.source, e.target])
        edge_pairs.add(pair)
        concept_map.setdefault(e.source, set()).add(e.target)
        concept_map.setdefault(e.target, set()).add(e.source)
    return frozenset(edge_pairs), {k: set(v) for k, v in concept_map.items()}


def jaccard_tokens(a: str, b: str) -> float:
    ta = set(a.lower().split())
    tb = set(b.lower().split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _author_score(p1: Any, p2: Any) -> float:
    aa = set(a.strip().lower() for a in p1.authors.split(",") if a.strip())
    ab = set(a.strip().lower() for a in p2.authors.split(",") if a.strip())
    return len(aa & ab) / max(len(aa | ab), 1)


def _abstract_score(p1: Any, p2: Any) -> float:
    return jaccard_tokens(p1.abstract, p2.abstract)


def _concept_score_prebuilt(pid1: str, pid2: str, concept_map: dict[str, set[str]]) -> float:
    c1 = concept_map.get(pid1, set())
    c2 = concept_map.get(pid2, set())
    if not c1 or not c2:
        return 0.0
    return len(c1 & c2) / len(c1 | c2)


def _edge_score_prebuilt(pid1: str, pid2: str, edge_pairs: frozenset) -> float:
    shared = 1 if frozenset([pid1, pid2]) in edge_pairs else 0
    return min(shared / 5.0, 1.0)


def _paper_text(p: Any) -> str:
    return f"{p.label}. {p.abstract}" if p.abstract else p.label


def _l2(v: list[float]) -> float:
    return math.sqrt(sum(x * x for x in v))


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def build_paper_embeddings(
    kg: KnowledgeGraph,
    llm: Any,
) -> dict[str, list[float]]:
    papers = kg.papers
    texts = [_paper_text(p) for p in papers]
    raw = llm.embed_parallel(texts)
    return {p.id: list(emb) for p, emb in zip(papers, raw)}


def _vector_score(
    emb1: list[float],
    emb2: list[float],
) -> float:
    dot = _dot(emb1, emb2)
    n1 = _l2(emb1)
    n2 = _l2(emb2)
    if n1 == 0 or n2 == 0:
        return 0.0
    return dot / (n1 * n2)


ALGORITHMS: dict[str, dict[str, Any]] = {
    "combined": {
        "label": "Combined (default)",
        "desc": "Authors + Abstract + Edges",
        "fn": lambda p1, p2, pid1, pid2, embs=None, edge_pairs=None, concept_map=None: (
            0.4 * _author_score(p1, p2)
            + 0.4 * _abstract_score(p1, p2)
            + (0.2 * _edge_score_prebuilt(pid1, pid2, edge_pairs) if edge_pairs is not None else 0.0)
        ),
    },
    "abstract": {
        "label": "Abstract Jaccard",
        "desc": "Abstract token overlap",
        "fn": lambda p1, p2, pid1, pid2, embs=None, edge_pairs=None, concept_map=None: _abstract_score(p1, p2),
    },
    "author": {
        "label": "Author Overlap",
        "desc": "Shared authors",
        "fn": lambda p1, p2, pid1, pid2, embs=None, edge_pairs=None, concept_map=None: _author_score(p1, p2),
    },
    "concept": {
        "label": "Concept Overlap",
        "desc": "Shared graph concepts",
        "fn": lambda p1, p2, pid1, pid2, embs=None, edge_pairs=None, concept_map=None: (
            _concept_score_prebuilt(pid1, pid2, concept_map) if concept_map is not None else 0.0
        ),
    },
    "vector": {
        "label": "Vector (semantic)",
        "desc": "Embedding cosine similarity",
        "fn": lambda p1, p2, pid1, pid2, embs=None, edge_pairs=None, concept_map=None: (
            _vector_score(embs[pid1], embs[pid2]) if embs and pid1 in embs and pid2 in embs else 0.0
        ),
    },
    "vector_combined": {
        "label": "Vector Combined",
        "desc": "Vector + Authors + Abstract + Edges",
        "fn": lambda p1, p2, pid1, pid2, embs=None, edge_pairs=None, concept_map=None: (
            0.5 * (_vector_score(embs[pid1], embs[pid2]) if embs and pid1 in embs and pid2 in embs else 0.0)
            + 0.2 * _author_score(p1, p2)
            + 0.2 * _abstract_score(p1, p2)
            + (0.1 * _edge_score_prebuilt(pid1, pid2, edge_pairs) if edge_pairs is not None else 0.0)
        ),
    },
}


def paper_similarity_matrix(
    kg: KnowledgeGraph,
    paper_ids: list[str] | None = None,
    algorithm: str = "combined",
    llm: Any = None,
    top_k: int | None = None,
) -> list[dict[str, Any]]:
    algo = ALGORITHMS.get(algorithm, ALGORITHMS["combined"])
    needs_vector = algorithm in ("vector", "vector_combined")
    papers = kg.papers
    if paper_ids:
        papers = [p for p in papers if p.id in paper_ids]
    embs = None
    if needs_vector and llm is not None:
        embs = build_paper_embeddings(kg, llm)
        papers = [p for p in papers if p.id in embs]

    # Pre-build lookup structures once — O(E) instead of O(N² × E)
    edge_pairs, concept_map = _build_lookups(kg)

    results = []
    for i, p1 in enumerate(papers):
        for p2 in papers[i + 1:]:
            score = algo["fn"](p1, p2, p1.id, p2.id, embs=embs, edge_pairs=edge_pairs, concept_map=concept_map)
            results.append({
                "source": p1.id,
                "source_title": p1.label,
                "target": p2.id,
                "target_title": p2.label,
                "score": round(score, 4),
                "author_overlap": round(_author_score(p1, p2), 4),
                "abstract_sim": round(_abstract_score(p1, p2), 4),
            })

    results.sort(key=lambda x: x["score"], reverse=True)

    if top_k is not None and top_k > 0:
        return results[:top_k]
    return results
