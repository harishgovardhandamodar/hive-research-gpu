"""Tests for the enhanced ResearchPool with caching, insights, and suggestions."""

from __future__ import annotations

import tempfile
from pathlib import Path

from hive_research.pool import ResearchPool


class MockPool(ResearchPool):
    """ResearchPool subclass that skips background threads and arXiv calls."""

    def __init__(self, store_dir: str | Path) -> None:
        self.store_dir = Path(store_dir)
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = str(self.store_dir / "pool.db")
        self._init_db()
        self._lock = __import__("threading").Lock()
        from hive_research.pool import LRUCache
        self._mem_cache = LRUCache(maxsize=64, ttl=300)
        self._sim_cache = {}
        self._sim_cache_dirty = True

        if not self._has_topics():
            self._seed_default_topics()


class TestResearchPool:
    def setup_method(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.pool = MockPool(self.tmp.name)

    def teardown_method(self) -> None:
        self.tmp.cleanup()

    def test_topics_seeded(self) -> None:
        topics = self.pool.get_topics()
        assert len(topics) >= 8
        assert any(t["name"] == "Knowledge graphs" for t in topics)

    def test_add_topic(self) -> None:
        self.pool.add_topic("Test Topic", "test query")
        topics = self.pool.get_topics()
        assert any(t["name"] == "Test Topic" for t in topics)

    def test_remove_topic(self) -> None:
        self.pool.add_topic("ToRemove", "remove query")
        self.pool.remove_topic("ToRemove")
        topics = self.pool.get_topics()
        assert not any(t["name"] == "ToRemove" for t in topics)

    def test_observe_and_get_papers(self) -> None:
        self.pool._observe({
            "arxiv_id": "9999.99999",
            "title": "Test Paper",
            "authors": [{"name": "Author One"}],
            "authors_str": "Author One",
            "published": "2025-01-01",
            "abstract": "This is a test abstract about machine learning.",
            "categories": ["cs.AI"],
            "pdf_url": "http://arxiv.org/pdf/9999.99999",
        }, "Test Topic")

        papers = self.pool.get_observed_papers()
        assert len(papers) >= 1
        assert papers[0]["arxiv_id"] == "9999.99999"

    def test_mark_imported(self) -> None:
        self.pool._observe({"arxiv_id": "8888.88888", "title": "Import Test"}, "Test")
        self.pool.mark_imported("8888.88888")
        papers = self.pool.get_observed_papers()
        imp = next(p for p in papers if p["arxiv_id"] == "8888.88888")
        assert imp["imported"] is True

    def test_get_insights(self) -> None:
        self.pool._observe({"arxiv_id": "p1", "title": "Paper One"}, "Topic A")
        self.pool._observe({"arxiv_id": "p2", "title": "Paper Two"}, "Topic A")
        self.pool._observe({"arxiv_id": "p3", "title": "Paper Three"}, "Topic B")
        self.pool.mark_imported("p1")
        insights = self.pool.get_insights()
        assert insights["total_papers"] >= 3
        assert insights["imported_papers"] >= 1
        assert "Topic A" in insights["topics"]
        assert insights["topics"]["Topic A"]["imported"] >= 1

    def test_get_suggestions_unknown_paper(self) -> None:
        suggestions = self.pool.get_suggestions("nonexistent")
        assert suggestions == []

    def test_get_suggestions_finds_similar(self) -> None:
        self.pool._observe({
            "arxiv_id": "target", "title": "Deep Learning for NLP",
            "abstract": "neural networks for natural language processing",
        }, "Topic")
        self.pool._observe({
            "arxiv_id": "similar1", "title": "Transformers in NLP",
            "abstract": "transformer models for natural language tasks",
        }, "Topic")
        self.pool._observe({
            "arxiv_id": "unrelated", "title": "Quantum Computing",
            "abstract": "quantum mechanics and computing theory",
        }, "Topic")

        suggestions = self.pool.get_suggestions("target", top_k=5)
        assert len(suggestions) >= 1
        # similar1 should be ranked before unrelated
        similar_ids = [s["arxiv_id"] for s in suggestions]
        assert "similar1" in similar_ids

    def test_get_pool_graph(self) -> None:
        self.pool._observe({"arxiv_id": "g1", "title": "Graph Paper One"}, "G")
        self.pool._observe({"arxiv_id": "g2", "title": "Graph Paper Two"}, "G")
        self.pool._rebuild_similarity_cache()
        graph = self.pool.get_pool_graph()
        assert "nodes" in graph
        assert "edges" in graph
        assert len(graph["nodes"]) >= 2

    def test_update_tags(self) -> None:
        self.pool._observe({"arxiv_id": "tag-test", "title": "Tag Test"}, "T")
        self.pool.update_tags("tag-test", ["tag1", "tag2"])
        papers = self.pool.get_observed_papers()
        tp = next(p for p in papers if p["arxiv_id"] == "tag-test")
        assert "tag1" in tp.get("tags", [])

    def test_mem_cache(self) -> None:
        # First call hits DB, second call hits memory
        _ = self.pool.get_topics()
        cached = self.pool._mem_cache.get("topics")
        assert cached is not None
        assert len(cached) >= 8
