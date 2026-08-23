"""Paper clustering for knowledge-graph navigation.

Groups papers into thematic clusters using the existing similarity
algorithms plus union-find over a score threshold. Labels are derived
from each cluster's most distinctive title tokens (tf/idf style).
"""

from __future__ import annotations

import logging
import threading
from collections import Counter
from typing import Any

from .jobs import utcnow
from .similarity import paper_similarity_matrix

logger = logging.getLogger(__name__)

STOPWORDS = {
    "the", "a", "an", "of", "for", "and", "to", "in", "on", "with", "via",
    "using", "based", "towards", "toward", "from", "by", "at", "as", "is",
    "are", "be", "can", "we", "our", "their", "its", "this", "that", "these",
    "those", "how", "what", "which", "when", "large", "language", "models",
    "model", "learning", "neural", "networks", "network", "deep", "approach",
    "framework", "study", "analysis", "towards", "improving", "paper",
}


class _UnionFind:
    def __init__(self, ids: list[str]) -> None:
        self.parent = {i: i for i in ids}

    def find(self, x: str) -> str:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def _cluster_label(titles: list[str], corpus_titles: list[str]) -> str:
    """Most distinctive tokens of the cluster vs the whole corpus."""
    cluster_tf = Counter()
    for t in titles:
        cluster_tf.update(w for w in t.lower().split() if len(w) > 2 and w not in STOPWORDS)
    if not cluster_tf:
        return "Misc"
    corpus_df = Counter()
    for t in corpus_titles:
        corpus_df.update(set(w.lower() for w in t.split()))
    n_docs = max(len(corpus_titles), 1)
    scored = [
        (cnt * (1 + (corpus_df[w] / n_docs)), w)
        for w, cnt in cluster_tf.items()
        if cnt >= 2 or len(titles) == 1
    ]
    scored.sort(reverse=True)
    words = [w.capitalize() for _, w in scored[:3]]
    return " · ".join(words) if words else "Misc"


def compute_paper_clusters(
    kg: Any,
    algorithm: str = "combined",
    threshold: float = 0.35,
    min_cluster_size: int = 2,
) -> dict[str, Any]:
    """Group papers into thematic clusters.

    Returns {"clusters": [{id,label,size,paper_ids,papers}], "assignment":
    {paper_id: cluster_id}, "unclustered": [ids], "params": {...}}.
    """
    papers = kg.papers
    paper_ids = [p.id for p in papers]
    titles = {p.id: p.label or p.id for p in papers}
    title_list = [titles[pid] for pid in paper_ids]

    pairs = paper_similarity_matrix(kg, algorithm=algorithm)
    uf = _UnionFind(paper_ids)
    linked = 0
    for row in pairs:
        if row["score"] >= threshold:
            uf.union(row["source"], row["target"])
            linked += 1

    components: dict[str, list[str]] = {}
    for pid in paper_ids:
        components.setdefault(uf.find(pid), []).append(pid)

    clusters = []
    assignment: dict[str, str] = {}
    unclustered: list[str] = []
    for i, (root, members) in enumerate(
        sorted(components.items(), key=lambda kv: -len(kv[1]))
    ):
        if len(members) < min_cluster_size:
            unclustered.extend(members)
            continue
        cid = f"c{i}"
        label = _cluster_label([titles[m] for m in members], title_list)
        clusters.append({
            "id": cid,
            "label": label,
            "size": len(members),
            "paper_ids": sorted(members),
            "papers": [{"id": m, "title": titles[m]} for m in sorted(members)],
        })
        for m in members:
            assignment[m] = cid

    logger.info(
        "Clustering (%s, thr=%.2f): %d clusters, %d unclustered, %d linked pairs",
        algorithm, threshold, len(clusters), len(unclustered), linked,
    )
    return {
        "clusters": clusters,
        "assignment": assignment,
        "unclustered": unclustered,
        "params": {
            "algorithm": algorithm,
            "threshold": threshold,
            "min_cluster_size": min_cluster_size,
            "papers": len(paper_ids),
        },
        "computed_at": utcnow().isoformat(),
    }


# Cache keyed by graph shape + params so UI toggling doesn't recompute O(N²)
_cache: dict[str, Any] = {}
_cache_lock = threading.Lock()


def _cache_key(kg: Any, algorithm: str, threshold: float) -> tuple:
    try:
        shape = (len(kg.papers), len(kg.edges))
    except Exception:
        shape = (0, 0)
    return (shape, algorithm, round(threshold, 3))


def get_paper_clusters(
    kg: Any,
    algorithm: str = "combined",
    threshold: float = 0.35,
    force: bool = False,
) -> dict[str, Any]:
    key = _cache_key(kg, algorithm, threshold)
    with _cache_lock:
        if not force and _cache.get("key") == key and _cache.get("data"):
            return _cache["data"]
    data = compute_paper_clusters(kg, algorithm=algorithm, threshold=threshold)
    with _cache_lock:
        _cache["key"] = key
        _cache["data"] = data
    return data
