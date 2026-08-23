from __future__ import annotations

import unittest
from unittest import mock

from hive_research.rag import RAGEngine
from hive_research.tests.base import FakeLLM, TempDirTestCase, make_config


def _fake_paper_text(topic_word: str, sentences: int = 60) -> str:
    return " ".join(
        f"sentence {i} about {topic_word} and agents" for i in range(sentences)
    )


class TestChunking(TempDirTestCase):
    def test_chunk_size_and_overlap(self) -> None:
        cfg = make_config(self.tmp)
        engine = RAGEngine.__new__(RAGEngine)
        engine.config = cfg
        words = " ".join(f"w{i}" for i in range(100))
        chunks = engine._chunk_text(words)
        self.assertEqual(len(chunks[0].split()), cfg.rag_chunk_size)
        # with overlap 8 and size 40, second chunk starts at word 32
        self.assertEqual(chunks[1].split()[0], "w32")
        # all words covered
        joined = " ".join(chunks)
        for i in (0, 39, 99):
            self.assertIn(f"w{i}", joined)


class TestIndexAndSearch(TempDirTestCase):
    def _engine(self) -> RAGEngine:
        cfg = make_config(self.tmp)
        llm = FakeLLM()
        kg = mock.Mock()
        node = mock.Mock()
        node.label = "Swarm Paper"
        kg.get_paper.return_value = node
        return RAGEngine(cfg, llm, kg)  # type: ignore[arg-type]

    def test_index_and_search_roundtrip(self) -> None:
        engine = self._engine()
        n = engine.index_paper("2401.1", _fake_paper_text("swarms"))
        self.assertGreater(n, 0)
        results = engine.search("swarms agents")
        self.assertTrue(results)
        self.assertEqual(results[0]["source_id"], "2401.1")
        self.assertIn("source_title", results[0])
        self.assertIn("score", results[0])

    def test_search_empty_index(self) -> None:
        engine = self._engine()
        self.assertEqual(engine.search("anything"), [])

    def test_reindex_replaces_duplicates(self) -> None:
        engine = self._engine()
        engine.index_paper("2401.2", _fake_paper_text("alignment", sentences=30))
        before = len(engine.chunks)
        engine.index_paper("2401.2", _fake_paper_text("alignment", sentences=30))
        self.assertEqual(len(engine.chunks), before)

    def test_answer_includes_sources(self) -> None:
        engine = self._engine()
        engine.index_paper("2401.3", _fake_paper_text("security"))
        out = engine.answer("what about security?")
        self.assertIn("answer", out)
        self.assertIn("sources", out)
        self.assertEqual(out["sources"][0]["id"], "2401.3")

    def test_answer_no_results_message(self) -> None:
        engine = self._engine()
        out = engine.answer("unknown topic")
        self.assertIn("No relevant", out["answer"])
        self.assertEqual(out["sources"], [])


if __name__ == "__main__":
    unittest.main()
