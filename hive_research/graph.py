from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from hive_datatype import (
    Edge,
    HiveGraph,
    Node,
    NodeType,
)

from .config import Config

logger = logging.getLogger(__name__)


class KnowledgeGraph:
    def __init__(self, config: Config, graph_id: str = "main") -> None:
        import threading

        self.config = config
        self.graph_id = graph_id
        self.graph_dir = Path(config.graph_dir)
        self.graph_dir.mkdir(parents=True, exist_ok=True)
        # The HTTP server is threaded; mutations + saves must not interleave.
        self._lock = threading.RLock()
        self._hive = self._load()

    def _path(self) -> Path:
        return self.graph_dir / f"{self.graph_id}.json"

    def _load(self) -> HiveGraph:
        path = self._path()
        if path.exists():
            try:
                hive = HiveGraph.from_json_file(str(path))
                valid_ids = {n.id for n in hive.nodes}
                before = len(hive.edges)
                hive.edges = [e for e in hive.edges if e.source in valid_ids and e.target in valid_ids]
                if len(hive.edges) < before:
                    logger.warning("Removed %d edges with invalid node refs", before - len(hive.edges))
                return hive
            except Exception as e:
                logger.warning("Failed to load graph, starting fresh: %s", e)
        return HiveGraph(id=self.graph_id)

    def save(self) -> None:
        with self._lock:
            tmp_path = self._path().with_suffix(".json.tmp")
            self._hive.to_json_file(str(tmp_path))
            os.replace(tmp_path, self._path())

    @property
    def hive(self) -> HiveGraph:
        return self._hive

    def add_paper(
        self,
        paper_id: str,
        title: str,
        authors: str = "",
        published: str = "",
        abstract: str = "",
        categories: list[str] | None = None,
        affiliations: str = "",
    ) -> Node:
        with self._lock:
            existing = self._hive.get_node(paper_id)
            if existing:
                if affiliations and not existing.affiliations:
                    existing.affiliations = affiliations
                    self.save()
                return existing
            node = Node(
                id=paper_id,
                type=NodeType.PAPER,
                label=title,
                graph_id=self.graph_id,
                arxiv_id=paper_id,
                authors=authors,
                published=published,
                abstract=abstract,
                categories=categories or [],
                affiliations=affiliations,
            )
            self._hive.nodes.append(node)
            return node

    def add_concept(
        self,
        concept_id: str,
        label: str,
        definition: str = "",
        concept_type: str = "concept",
    ) -> Node:
        with self._lock:
            existing = self._hive.get_node(concept_id)
            if existing:
                return existing
            node = Node(
                id=concept_id,
                type=NodeType.CONCEPT,
                label=label,
                graph_id=self.graph_id,
                definition=definition,
                concept_type=concept_type,
            )
            self._hive.nodes.append(node)
            return node

    def add_edge(
        self,
        source: str,
        target: str,
        relation: str = "related_to",
    ) -> Edge:
        from hive_datatype import validate_relation

        relation = validate_relation(relation)
        with self._lock:
            for e in self._hive.edges:
                if e.source == source and e.target == target and e.relation == relation:
                    return e
            edge = Edge(source=source, target=target, relation=relation)
            self._hive.edges.append(edge)
            return edge

    def find_similar_concept(
        self,
        label: str,
        threshold: float | None = None,
    ) -> Node | None:
        threshold = threshold if threshold is not None \
            else self.config.graph_similarity_threshold
        label_lower = label.lower()
        label_tokens = set(label_lower.split())
        best_score = 0.0
        best_node: Node | None = None
        for node in self._hive.concepts:
            node_tokens = set(node.label.lower().split())
            if not node_tokens or not label_tokens:
                continue
            intersection = label_tokens & node_tokens
            union = label_tokens | node_tokens
            score = len(intersection) / len(union) if union else 0.0
            if score > best_score:
                best_score = score
                best_node = node
        if best_score >= threshold and best_node is not None:
            return best_node
        return None

    def get_paper(self, paper_id: str) -> Node | None:
        return self._hive.get_node(paper_id)

    def get_concept(self, concept_id: str) -> Node | None:
        return self._hive.get_node(concept_id)

    @property
    def papers(self) -> list[Node]:
        return self._hive.papers

    @property
    def concepts(self) -> list[Node]:
        return self._hive.concepts

    @property
    def edges(self) -> list[Edge]:
        return self._hive.edges

    def stats(self) -> dict[str, int]:
        s = self._hive.stats
        return {
            "papers": s.papers,
            "graph_papers": s.graph_papers,
            "concepts": s.concepts,
            "graph_refs": s.graph_refs,
            "relations": s.relations,
            "cross_edges": s.cross_edges,
        }

    def to_node_link(self) -> dict[str, Any]:
        data = self._hive.to_node_link_dict()
        valid_ids = {n["id"] for n in data.get("nodes", [])}
        data["links"] = [
            l for l in data.get("links", [])
            if l.get("source") in valid_ids and l.get("target") in valid_ids
        ]
        return data

    # -- Snapshots for Fox companion save/load -------------------------------

    def _snapshots_dir(self) -> Path:
        d = self.graph_dir / "snapshots"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _sanitize_snapshot_name(self, name: str) -> str:
        import re as _re
        name = (name or "").strip()
        if not name:
            raise ValueError("snapshot name required")
        # allow letters, numbers, _, -, .
        if not _re.fullmatch(r"[A-Za-z0-9._-]{1,64}", name):
            raise ValueError("snapshot name must be 1-64 chars of [A-Za-z0-9._-]")
        return name

    def save_snapshot(self, name: str) -> dict[str, Any]:
        safe = self._sanitize_snapshot_name(name)
        dest = self._snapshots_dir() / f"{safe}.json"
        with self._lock:
            tmp = dest.with_suffix(".json.tmp")
            self._hive.to_json_file(str(tmp))
            os.replace(tmp, dest)
        return {"path": str(dest), "name": safe, "nodes": len(self._hive.nodes), "edges": len(self._hive.edges)}

    def load_snapshot(self, name: str, merge: bool = False) -> dict[str, Any]:
        safe = self._sanitize_snapshot_name(name)
        src = self._snapshots_dir() / f"{safe}.json"
        if not src.exists():
            # also try graph_dir/{name}.json for backwards compat
            alt = self.graph_dir / f"{safe}.json"
            if alt.exists():
                src = alt
            else:
                raise FileNotFoundError(f"snapshot not found: {safe}")
        loaded = HiveGraph.from_json_file(str(src))
        with self._lock:
            if merge:
                existing_ids = {n.id for n in self._hive.nodes}
                added_nodes = 0
                for n in loaded.nodes:
                    if n.id not in existing_ids:
                        self._hive.nodes.append(n)
                        added_nodes += 1
                existing_edges = {(e.source, e.target, e.relation) for e in self._hive.edges}
                added_edges = 0
                for e in loaded.edges:
                    if (e.source, e.target, e.relation) not in existing_edges:
                        self._hive.edges.append(e)
                        added_edges += 1
                self.save()
                return {
                    "path": str(src),
                    "name": safe,
                    "merged": True,
                    "added_nodes": added_nodes,
                    "added_edges": added_edges,
                    "total_nodes": len(self._hive.nodes),
                    "total_edges": len(self._hive.edges),
                }
            else:
                self._hive = loaded
                self.graph_id = loaded.id or self.graph_id
                self.save()
                return {
                    "path": str(src),
                    "name": safe,
                    "merged": False,
                    "nodes": len(self._hive.nodes),
                    "edges": len(self._hive.edges),
                }

    def list_snapshots(self) -> list[dict[str, Any]]:
        d = self._snapshots_dir()
        out: list[dict[str, Any]] = []
        for p in sorted(d.glob("*.json")):
            try:
                st = p.stat()
                out.append({"name": p.stem, "path": str(p), "size": st.st_size, "mtime": int(st.st_mtime)})
            except OSError:
                continue
        # also surface legacy graph_dir/*.json snapshots (excluding main)
        for p in sorted(self.graph_dir.glob("*.json")):
            if p.stem in ("main",):
                continue
            if p.parent == d:
                continue
            try:
                st = p.stat()
                out.append({"name": p.stem, "path": str(p), "size": st.st_size, "mtime": int(st.st_mtime), "legacy": True})
            except OSError:
                continue
        return out

    def detail_graph(self, llm: Any) -> int:
        node_map = {n.id: n.label for n in self._hive.nodes}
        batch: list[dict[str, str]] = []
        edges_to_detail: list[Edge] = []
        for e in self._hive.edges:
            src_label = node_map.get(e.source, e.source)
            tgt_label = node_map.get(e.target, e.target)
            if not e.detail.strip():
                batch.append({
                    "source_id": e.source,
                    "source_label": src_label,
                    "target_label": tgt_label,
                    "relation": e.relation,
                })
                edges_to_detail.append(e)
        if not batch:
            return 0

        system_msg = "You are a research knowledge graph assistant."
        user_prompt = (
            "For each triple below, write ONE short sentence describing the relationship "
            "between the two nodes. Be specific and informative. "
            "Return ONLY a JSON array of strings in the same order:\n"
            + "\n".join(
                f"- {b['source_label']} --[{b['relation']}]--> {b['target_label']}"
                for b in batch
            )
        )
        raw = llm.chat(
            [{"role": "system", "content": system_msg},
             {"role": "user", "content": user_prompt}],
            temperature=0.1,
        )
        content = raw.get("content", "") if isinstance(raw, dict) else str(raw)
        try:
            details = json.loads(content)
            if not isinstance(details, list):
                details = [str(details)]
        except json.JSONDecodeError:
            import re
            matches = re.findall(r'"(.*?)"', content)
            details = matches if matches else [content]
        count = 0
        for e, d in zip(edges_to_detail, details):
            if isinstance(d, str) and d.strip():
                e.detail = d.strip()[:200]
                count += 1
        self.save()
        return count
