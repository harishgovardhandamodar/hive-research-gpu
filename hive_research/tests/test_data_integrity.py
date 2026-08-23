"""P0 data-integrity regression tests.

Covers the three silent-corruption bugs: RAG index/vector desync,
non-atomic PDF downloads, and Fox conversation write races.
"""

from __future__ import annotations

import json
import threading
import unittest
from unittest import mock

import numpy as np

from hive_research.arxiv_fetcher import download_pdf
from hive_research.fox import Fox
from hive_research.graph import KnowledgeGraph
from hive_research.rag import RAGEngine
from hive_research.tests.base import FakeLLM, TempDirTestCase, make_config


def make_rag(tmp) -> RAGEngine:
    cfg = make_config(tmp)
    llm = FakeLLM()
    kg = KnowledgeGraph(cfg, graph_id="p0")
    return RAGEngine(cfg, llm, kg)


class TestRagDesync(TempDirTestCase):
    def _seed(self, engine: RAGEngine) -> None:
        kg = engine.kg
        node = mock.Mock()
        node.label = "T"
        kg.get_paper = mock.Mock(return_value=node)
        engine.index_paper("2401.1", "alignment agents reward models " * 30)

    def test_load_detects_length_mismatch_and_discards_vectors(self) -> None:
        engine = make_rag(self.tmp)
        self._seed(engine)
        # simulate crash between the two file writes
        np.save(str(engine._embeddings_path()), np.zeros((2, 128), dtype=np.float32))

        reloaded = make_rag(self.tmp)
        self.assertEqual(len(reloaded.chunks), len(engine.chunks))
        self.assertIsNone(reloaded.embeddings)          # vectors rejected
        self.assertEqual(reloaded.search("alignment"), [])  # safe, no wrong cites

    def test_truncated_index_json_recovers_empty(self) -> None:
        engine = make_rag(self.tmp)
        self._seed(engine)
        engine._index_path().write_text("{corrupt json")
        reloaded = make_rag(self.tmp)
        self.assertEqual(reloaded.chunks, [])
        self.assertIsNone(reloaded.embeddings)

    def test_rebuild_restores_searchability(self) -> None:
        engine = make_rag(self.tmp)
        self._seed(engine)
        engine.embeddings = None  # as after desync recovery
        result = engine.rebuild()
        self.assertEqual(result["status"], "ok")
        self.assertIsNotNone(engine.embeddings)
        results = engine.search("alignment agents")
        self.assertTrue(results)
        self.assertEqual(results[0]["source_id"], "2401.1")


class TestAtomicPdfDownload(TempDirTestCase):
    def _download(self, tmp, content: bytes):
        target_dir = tmp / "papers"
        with mock.patch("requests.get") as get:
            get.return_value = mock.Mock(
                raise_for_status=lambda: None,
                content=content,
            )
            result = download_pdf("2401.9", target_dir)
        return result, target_dir

    def test_valid_pdf_lands_atomically(self) -> None:
        payload = b"%PDF-1.7 " + b"x" * 20480
        result, target_dir = self._download(self.tmp, payload)
        self.assertIsNotNone(result)
        self.assertTrue((target_dir / "2401.9.pdf").exists())
        self.assertFalse((target_dir / "2401.9.pdf.part").exists())  # renamed away
        self.assertEqual((target_dir / "2401.9.pdf").read_bytes(), payload)

    def test_html_error_page_never_becomes_a_pdf(self) -> None:
        bad = b"<html><body>rate limited</body></html>"
        result, target_dir = self._download(self.tmp, bad)
        self.assertIsNone(result)
        self.assertFalse((target_dir / "2401.9.pdf").exists())
        self.assertFalse((target_dir / "2401.9.pdf.part").exists())

    def test_tiny_file_rejected(self) -> None:
        result, target_dir = self._download(self.tmp, b"%PDF-1.4 tiny")
        self.assertIsNone(result)
        self.assertFalse((target_dir / "2401.9.pdf").exists())

    def test_network_failure_leaves_no_part_file(self) -> None:
        target_dir = self.tmp / "papers"
        with mock.patch("requests.get", side_effect=ConnectionError("boom")):
            result = download_pdf("2401.8", target_dir)
        self.assertIsNone(result)
        self.assertFalse((target_dir / "2401.8.pdf.part").exists())


class TestFoxConversationRace(TempDirTestCase):
    def test_concurrent_turns_all_persisted(self) -> None:
        cfg = make_config(self.tmp)
        cfg.data["fox"] = {"history_limit": 500}  # keep every turn: no trim masking races
        llm = FakeLLM()
        fox = Fox(cfg, llm, KnowledgeGraph(cfg, graph_id="race"), _dummy_rag(cfg, llm))
        n_threads, per_thread = 8, 3
        barrier = threading.Barrier(n_threads)

        def worker(t: int) -> None:
            barrier.wait()  # maximize contention on one conversation
            for i in range(per_thread):
                fox.chat(f"msg {t}-{i}", mode="fast", conversation_id="raceconv")

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        conv = fox.get_conversation("raceconv")
        self.assertIsNotNone(conv)
        # every user+assistant turn survived: no lost updates, no corruption
        self.assertEqual(len(conv["messages"]), n_threads * per_thread * 2)
        roles = [m["role"] for m in conv["messages"]]
        self.assertTrue(all(r in ("user", "assistant") for r in roles))


def _dummy_rag(cfg, llm):
    from hive_research.rag import RAGEngine

    return RAGEngine(cfg, llm, KnowledgeGraph(cfg, graph_id="race-rag"))


if __name__ == "__main__":
    unittest.main()
