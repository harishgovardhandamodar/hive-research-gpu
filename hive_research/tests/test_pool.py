from __future__ import annotations

import unittest

from hive_research.pool import ResearchPool
from hive_research.tests.base import TempDirTestCase


class TestResearchPool(TempDirTestCase):
    def _pool(self, **kwargs) -> ResearchPool:
        defaults = dict(store_dir=self.tmp / "pool", auto_refresh=False)
        defaults.update(kwargs)
        return ResearchPool(**defaults)

    def test_default_topics_seeded(self) -> None:
        pool = self._pool()
        topics = pool.get_topics()
        self.assertTrue(topics)
        names = {t["name"] for t in topics}
        self.assertIn("AI alignment", names)

    def test_seed_domain_presets(self) -> None:
        pool = self._pool(seed_domain_presets=["swarms", "llm-security"])
        names = {t["name"] for t in pool.get_topics()}
        self.assertIn("Agent swarms", names)
        self.assertIn("Jailbreaks", names)

    def test_seed_domain_idempotent(self) -> None:
        pool = self._pool(seed_domain_presets=["agents"])
        before = len(pool.get_topics())
        added = pool.seed_domain("agents")
        self.assertEqual(added, 0)
        self.assertEqual(len(pool.get_topics()), before)

    def test_add_remove_topic(self) -> None:
        pool = self._pool()
        pool.add_topic("Custom", "custom query")
        names = {t["name"] for t in pool.get_topics()}
        self.assertIn("Custom", names)
        pool.remove_topic("Custom")
        self.assertNotIn("Custom", {t["name"] for t in pool.get_topics()})

    def test_observe_and_dedup(self) -> None:
        pool = self._pool()
        entry = {
            "arxiv_id": "2401.9",
            "title": "Agent Paper",
            "authors": ["Fox"],
            "authors_str": "Fox",
            "published": "2024-01-01",
            "abstract": "About agents.",
            "categories": ["cs.MA"],
            "pdf_url": "http://x/y.pdf",
        }
        pool._observe(entry, "LLM agents")
        pool._observe(entry, "AI alignment")  # same paper, second topic
        papers = pool.get_observed_papers()
        self.assertEqual(len(papers), 1)
        self.assertEqual(set(papers[0]["topics"]), {"LLM agents", "AI alignment"})

    def test_mark_imported(self) -> None:
        pool = self._pool()
        entry = {
            "arxiv_id": "2401.10",
            "title": "T",
            "authors": [],
            "authors_str": "",
            "published": "",
            "abstract": "",
            "categories": [],
            "pdf_url": "",
        }
        pool._observe(entry, "topic")
        pool.mark_imported("2401.10")
        paper = pool.get_observed_papers()[0]
        self.assertTrue(paper["imported"])
        self.assertIsNotNone(paper["imported_at"])

    def test_update_tags(self) -> None:
        pool = self._pool()
        entry = {
            "arxiv_id": "2401.11",
            "title": "T",
            "authors": [],
            "authors_str": "",
            "published": "",
            "abstract": "",
            "categories": [],
            "pdf_url": "",
        }
        pool._observe(entry, "topic")
        pool.update_tags("2401.11", ["swarm", "novel"])
        paper = pool.get_observed_papers()[0]
        self.assertEqual(paper["tags"], ["swarm", "novel"])

    def test_pool_graph_shape(self) -> None:
        pool = self._pool()
        for i in range(3):
            pool._observe(
                {
                    "arxiv_id": f"2401.{i}",
                    "title": f"paper about swarm agents number {i} swarm",
                    "authors": [],
                    "authors_str": "",
                    "published": "",
                    "abstract": "swarm agents coordination swarm",
                    "categories": [],
                    "pdf_url": "",
                },
                "Agent swarms",
            )
        graph = pool.get_pool_graph()
        self.assertEqual(len(graph["nodes"]), 3)
        self.assertTrue(all("label" in n and "topics" in n for n in graph["nodes"]))
        self.assertTrue(all("source" in e and "target" in e for e in graph["edges"]))


if __name__ == "__main__":
    unittest.main()
