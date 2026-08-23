from __future__ import annotations

import json
import unittest
from unittest import mock

from hive_research.parser import extract_text_pages
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


def make_rag_engine(tmp) -> RAGEngine:
    cfg = make_config(tmp)
    llm = FakeLLM()
    kg = mock.Mock()
    node = mock.Mock()
    node.label = "Swarm Paper"
    kg.get_paper.return_value = node
    return RAGEngine(cfg, llm, kg)  # type: ignore[arg-type]


class TestIndexAndSearch(TempDirTestCase):
    def _engine(self) -> RAGEngine:
        return make_rag_engine(self.tmp)

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


class TestPageAwareIndexing(TempDirTestCase):
    def _engine(self) -> RAGEngine:
        cfg = make_config(self.tmp)
        llm = FakeLLM()
        kg = mock.Mock()
        node = mock.Mock()
        node.label = "Paged Paper"
        kg.get_paper.return_value = node
        return RAGEngine(cfg, llm, kg)  # type: ignore[arg-type]

    def test_chunks_carry_page_numbers(self) -> None:
        engine = self._engine()
        pages = [
            {"page": 1, "text": "introduction about alignment methods " * 30},
            {"page": 2, "text": "experiments on multi agent debate " * 30},
        ]
        n = engine.index_paper("2402.1", "\n".join(p["text"] for p in pages), pages=pages)
        self.assertGreater(n, 0)
        self.assertTrue(all(c.page_start == c.page_end and c.page_start > 0 for c in engine.chunks))
        hit = engine.search("multi agent debate experiments")[0]
        self.assertEqual(hit["page"], 2)

    def test_legacy_plain_text_index_still_works(self) -> None:
        engine = self._engine()
        n = engine.index_paper("2402.2", "plain text without pages " * 50)
        self.assertGreater(n, 0)
        self.assertTrue(all(c.page_start == 0 for c in engine.chunks))

    def test_old_index_without_page_fields_loads(self) -> None:
        engine = self._engine()
        engine.index_paper("2402.3", "legacy chunk content " * 40)
        # rewrite index.json in the OLD schema (no page fields)
        old = [{"text": c.text, "source_id": c.source_id,
                "source_title": c.source_title, "chunk_idx": c.chunk_idx}
               for c in engine.chunks]
        engine._index_path().write_text(json.dumps(old))

        reloaded = self._engine()
        reloaded._load()
        self.assertEqual(len(reloaded.chunks), len(engine.chunks))
        self.assertTrue(all(c.page_start == 0 for c in reloaded.chunks))


if __name__ == "__main__":
    unittest.main()


class TestHybridRetrieval(TempDirTestCase):
    def _engine(self):
        return make_rag_engine(self.tmp)

    def test_exact_acronym_ranks_via_lexical(self) -> None:
        engine = self._engine()
        # chunk A: dense-similar vocabulary but no acronym
        engine.index_paper("2403.1", "reinforcement learning from feedback reward models " * 20)
        # chunk B: contains the exact identifier once among filler
        engine.index_paper("2403.2", "GRPO policy optimization trick " + "filler words here " * 18)
        results = engine.search("GRPO")
        self.assertTrue(results)
        self.assertEqual(results[0]["source_id"], "2403.2",
                         "exact acronym hit must outrank vocabulary-only match")
        self.assertGreater(results[0]["lexical_score"], 0)

    def test_scores_exposed(self) -> None:
        engine = self._engine()
        engine.index_paper("2403.3", "swarm coordination pheromones " * 25)
        r = engine.search("swarm coordination")[0]
        self.assertIn("dense_score", r)
        self.assertIn("lexical_score", r)
        self.assertAlmostEqual(r["score"], 0.65 * r["dense_score"] + 0.35 * r["lexical_score"], places=2)


class TestEmbedModelStamping(TempDirTestCase):
    def test_meta_written_and_model_switch_invalidates(self) -> None:
        cfg = make_config(self.tmp)
        kg = mock.Mock()
        node = mock.Mock(); node.label = "T"
        kg.get_paper.return_value = node
        engine = RAGEngine(cfg, FakeLLM(), kg)
        engine.index_paper("2404.2", "content for stamping " * 30)

        import json as _json
        meta = _json.loads(engine._meta_path().read_text())
        self.assertEqual(meta["embed_model"], cfg.ollama_embed_model)
        self.assertEqual(meta["chunks"], len(engine.chunks))

        # researcher switches embed model; same store -> vectors rejected on load
        engine.config.data["ollama"]["embed_model"] = "other-model"
        engine2 = RAGEngine(engine.config, FakeLLM(), kg)
        self.assertIsNone(engine2.embeddings)
        self.assertEqual(len(engine2.chunks), len(engine.chunks))  # texts kept for rebuild
        self.assertEqual(engine2.search("anything"), [])           # safe: no search


class TestExtractTextPages(TempDirTestCase):
    def test_returns_numbered_nonempty_pages(self) -> None:
        import fitz

        doc = fitz.open()
        for body in ("page one text", "", "page three text"):
            page = doc.new_page()
            if body:
                page.insert_text((72, 72), body)
        path = self.tmp / "t.pdf"
        doc.save(str(path))
        doc.close()

        pages = extract_text_pages(path)
        self.assertEqual([p["page"] for p in pages], [1, 3])  # empty page skipped
        self.assertIn("page one", pages[0]["text"])
