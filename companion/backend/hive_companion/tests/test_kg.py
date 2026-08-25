from __future__ import annotations

import asyncio
import unittest

from hive_companion.kg import KGCache, extract_arxiv_ids


def _graph() -> dict:
    return {
        "nodes": [
            {"id": "2202.09061v4", "label": "VLP: A Survey on Vision-Language Pre-Training", "type": "paper",
             "abstract": "vision language pre training models survey"},
            {"id": "2107.01994v1", "label": "Template-Based Graph Clustering", "type": "paper",
             "abstract": "template based clustering of graphs"},
            {"id": "vl_pretraining", "label": "vision-language pre-training", "type": "concept",
             "definition": "joint representation learning"},
            {"id": "graph_clustering", "label": "graph clustering", "type": "concept"},
        ],
        "links": [
            {"source": "2202.09061v4", "target": "vl_pretraining", "relation": "related_to"},
            {"source": "2107.01994v1", "target": "graph_clustering", "relation": "related_to"},
            {"source": "2202.09061v4", "target": "2107.01994v1", "relation": "cites"},
        ],
    }


def _cache() -> KGCache:
    cache = KGCache.__new__(KGCache)
    cache.client = None
    cache._graph = _graph()
    cache._loaded_at = 9e9  # fresh
    return cache


class TestExtractIds(unittest.TestCase):
    def test_frontmatter_wins(self) -> None:
        content = "---\narxiv_id: 2202.09061v4\n---\n# Notes citing 2401.12345\n"
        self.assertEqual(extract_arxiv_ids(content)[0], "2202.09061v4")

    def test_regex_fallback(self) -> None:
        content = "Discusses 2401.12345 and arxiv 2308.14179v1."
        ids = extract_arxiv_ids(content)
        self.assertEqual(ids, ["2401.12345", "2308.14179v1"])

    def test_no_duplicates_by_base(self) -> None:
        content = "See 2401.12345v2 and 2401.12345."
        self.assertEqual(len(extract_arxiv_ids(content)), 1)


class TestKGViews(unittest.TestCase):
    def test_slim_drops_heavy_fields(self) -> None:
        slim = asyncio.run(_cache().slim())
        node = next(n for n in slim["nodes"] if n["id"] == "2202.09061v4")
        self.assertNotIn("abstract", node)
        self.assertEqual(node["label"], "VLP: A Survey on Vision-Language Pre-Training")
        self.assertEqual(len(slim["links"]), 3)

    def test_related_scores_shared_concepts_and_cites(self) -> None:
        related = asyncio.run(_cache().related_subgraph(["2202.09061v4"]))
        papers = {p["id"]: p for p in related["papers"]}
        # direct cite scores higher than nothing
        self.assertIn("2107.01994v1", papers)
        self.assertTrue(papers["2107.01994v1"]["direct"])
        concepts = {c["id"] for c in related["concepts"]}
        self.assertIn("vl_pretraining", concepts)
        self.assertIn("vision-language pre-training", related["keywords"])

    def test_search_matches_label_over_abstract(self) -> None:
        import asyncio

        result = asyncio.run(_cache().search("clustering"))
        ids = {n["id"] for n in result["nodes"]}
        self.assertIn("2107.01994v1", ids)
        self.assertIn("graph_clustering", ids)
        kw = [k["label"] for k in result.get("keywords", [])]
        self.assertIn("graph clustering", kw)

    def test_search_empty_query(self) -> None:
        import asyncio

        result = asyncio.run(_cache().search("zzz"))
        self.assertEqual(result["nodes"], [])


if __name__ == "__main__":
    unittest.main()
