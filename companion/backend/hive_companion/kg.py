"""Knowledge-graph access: cached load, slim view, search-driven sub-graphs,
and per-artifact related-paper extraction."""

from __future__ import annotations

import re
import time
from collections import defaultdict
from typing import Any

from .hive_client import HiveClient

ARXIV_RE = re.compile(r"\b(\d{4}\.\d{4,5})(v\d+)?\b")
TTL_S = 300


def _tokenize(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", text.lower()) if len(t) > 2}


def extract_arxiv_ids(content: str, limit: int = 3) -> list[str]:
    """Frontmatter arxiv_id wins; otherwise ids mentioned in the text."""
    ids: list[str] = []
    bases: set[str] = set()
    match = re.search(r"^arxiv_id:\s*(\d{4}\.\d{4,5})(v\d+)?\s*$", content, re.MULTILINE)
    if match:
        ids.append(match.group(0).split(":", 1)[1].strip())
        bases.add(match.group(1))
    for m in ARXIV_RE.finditer(content):
        base = m.group(1)
        if base not in bases:
            ids.append(m.group(0))
            bases.add(base)
        if len(ids) >= limit:
            break
    return ids[:limit]


class KGCache:
    """TTL-cached raw graph plus indexes for search and sub-graph shaping."""

    def __init__(self, client: HiveClient) -> None:
        self.client = client
        self._graph: dict[str, Any] | None = None
        self._loaded_at: float = 0.0

    def invalidate(self) -> None:
        self._graph = None

    async def get(self) -> dict[str, Any]:
        if self._graph is None or time.time() - self._loaded_at > TTL_S:
            self._graph = await self.client.get("/api/graph")
            self._loaded_at = time.time()
        return self._graph

    def _indexes(self) -> tuple[dict[str, dict], dict[str, list[dict]]]:
        g = self._graph or {}
        by_id = {n["id"]: n for n in g.get("nodes", [])}
        adj: dict[str, list[dict]] = defaultdict(list)
        for link in g.get("links", []):
            adj[link["source"]].append(link)
            adj[link["target"]].append({**link, "source": link["target"], "target": link["source"]})
        return by_id, adj

    # -- views ---------------------------------------------------------------

    def slim(self) -> dict[str, Any]:
        """Nodes without heavy fields — enough to render the global graph."""
        g = self._graph or {}
        nodes = [
            {
                "id": n["id"],
                "label": n.get("label") or n.get("title") or n["id"],
                "type": n.get("type", "paper"),
            }
            for n in g.get("nodes", [])
        ]
        links = [
            {"source": l["source"], "target": l["target"], "relation": l.get("relation", "related_to")}
            for l in g.get("links", [])
        ]
        return {"nodes": nodes, "links": links}

    async def search(self, query: str, max_nodes: int = 48) -> dict[str, Any]:
        """Dynamic sub-graph for a free-text query.

        Scores every node by token overlap (title/label weighted above paper
        abstract), keeps the strongest seeds, then expands one hop so the
        result carries its surrounding papers AND concepts.
        """
        await self.get()
        tokens = _tokenize(query)
        by_id, adj = self._indexes()
        if not tokens:
            return {"query": query, "nodes": [], "links": [], "matched": 0}

        scored: list[tuple[float, str]] = []
        for nid, node in by_id.items():
            label = (node.get("label") or node.get("title") or "").lower()
            text = label
            if node.get("type") == "paper":
                text += " " + (node.get("abstract") or "").lower()
            score = sum(2.0 if t in label else 0.0 for t in tokens) + sum(1.0 for t in tokens if t in text)
            if score > 0:
                scored.append((score, nid))
        scored.sort(reverse=True)

        seeds = {nid for _, nid in scored[:12]}
        included = set(seeds)
        for nid in list(seeds):
            for link in adj.get(nid, [])[:14]:
                included.add(link["target"])
        included = set(list(included)[:max_nodes])

        nodes = [
            {
                "id": nid,
                "label": by_id[nid].get("label") or by_id[nid].get("title") or nid,
                "type": by_id[nid].get("type", "paper"),
                "seed": nid in seeds,
                **(
                    {"definition": by_id[nid]["definition"]}
                    if by_id[nid].get("type") == "concept" and by_id[nid].get("definition")
                    else {}
                ),
            }
            for nid in included
        ]
        links = [
            {"source": l["source"], "target": l["target"], "relation": l.get("relation", "related_to")}
            for l in (self._graph or {}).get("links", [])
            if l["source"] in included and l["target"] in included
        ]
        # keywords = concepts in the sub-graph, strongest connectivity first
        sub_degree: dict[str, int] = defaultdict(int)
        for l in links:
            sub_degree[l["source"]] += 1
            sub_degree[l["target"]] += 1
        keywords = [
            {
                "id": nid,
                "label": by_id[nid].get("label", nid),
                "weight": sub_degree.get(nid, 0),
                **({"definition": by_id[nid]["definition"]} if by_id[nid].get("definition") else {}),
            }
            for nid in sorted(included, key=lambda n: -sub_degree.get(n, 0))
            if by_id.get(nid, {}).get("type") == "concept"
        ][:10]
        return {"query": query, "nodes": nodes, "links": links, "matched": len(seeds), "keywords": keywords}

    def related_subgraph(self, seed_ids: list[str]) -> dict[str, Any]:
        """Papers connected to the seeds via shared concepts or direct edges."""
        by_id, adj = self._indexes()
        seeds = [s for s in seed_ids if s in by_id]
        concepts: dict[str, int] = {}
        paper_scores: dict[str, float] = {}
        direct: set[str] = set()

        for sid in seeds:
            for link in adj.get(sid, []):
                other = link["target"]
                other_node = by_id.get(other)
                if other_node is None:
                    continue
                rel = link.get("relation", "related_to")
                if other_node.get("type") == "concept":
                    concepts[other] = concepts.get(other, 0) + 1
                else:
                    weight = 2.0 if rel in ("cites", "extends") else 1.5
                    paper_scores[other] = paper_scores.get(other, 0) + weight
                    direct.add(other)

        for cid in list(concepts):
            for link in adj.get(cid, []):
                other = link["target"]
                if other in by_id and by_id[other].get("type") == "paper" and other not in seeds:
                    paper_scores[other] = paper_scores.get(other, 0) + 0.75

        ranked = sorted(paper_scores.items(), key=lambda kv: kv[1], reverse=True)[:8]
        top_concepts = sorted(concepts.items(), key=lambda kv: kv[1], reverse=True)[:10]

        return {
            "seeds": [{"id": s, "label": by_id[s].get("label", s)} for s in seeds],
            "papers": [
                {"id": pid, "label": by_id[pid].get("label", pid), "score": round(score, 2), "direct": pid in direct}
                for pid, score in ranked
            ],
            "concepts": [
                {"id": cid, "label": by_id[cid].get("label", cid), "links": count}
                for cid, count in top_concepts
            ],
            "keywords": [by_id[cid].get("label", cid) for cid, _ in top_concepts],
        }
