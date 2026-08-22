from __future__ import annotations

import json
import unittest
from unittest import mock

from hive_research.fox import FOX_MODES, Fox, looks_like_status_query
from hive_research.feedback import FeedbackStore, parse_rating
from hive_research.jobs import JobRegistry
from hive_research.rag import RAGEngine
from hive_research.graph import KnowledgeGraph
from hive_research.tests.base import FakeLLM, TempDirTestCase, make_config


class ScriptedLLM(FakeLLM):
    """FakeLLM that returns canned answers per call order."""

    def __init__(self, answers: list[str]) -> None:
        super().__init__()
        self.answers = list(answers)
        self.prompts: list[str] = []

    def generate(self, prompt, **kwargs):
        self.prompts.append(prompt)
        return self.answers.pop(0) if self.answers else "fallback"


def make_fox(tmp, llm=None) -> tuple[Fox, RAGEngine]:
    cfg = make_config(tmp)
    llm = llm or FakeLLM()
    kg = KnowledgeGraph(cfg, graph_id="fox-test")
    rag = RAGEngine(cfg, llm, kg)
    return Fox(cfg, llm, kg, rag), rag


class TestFoxModesRegistry(unittest.TestCase):
    def test_all_required_modes_present(self) -> None:
        for mode in ("fast", "rag", "thinking", "deep-thinking", "deep-research", "survey"):
            self.assertIn(mode, FOX_MODES)
            self.assertTrue(FOX_MODES[mode]["description"])

    def test_descriptions_unique(self) -> None:
        desc = [m["description"] for m in FOX_MODES.values()]
        self.assertEqual(len(desc), len(set(desc)))


class TestFoxGrounding(TempDirTestCase):
    def _seed(self, fox: Fox, rag: RAGEngine) -> None:
        rag.index_paper("2401.42", "Swarm agents coordinate via local rules and pheromone fields. " * 20)

    def test_rag_grounded_answer_cites_sources(self) -> None:
        llm = ScriptedLLM(["Swarms use pheromones [1]."])
        fox, rag = make_fox(self.tmp, llm)
        self._seed(fox, rag)
        out = fox.chat("how do swarm agents coordinate?", mode="rag")
        self.assertTrue(out["grounded"])
        self.assertEqual(out["sources"][0]["source_id"], "2401.42")
        self.assertIn("Context:", llm.prompts[-1])
        self.assertIn("[1]", llm.prompts[-1])

    def test_rag_empty_index_reports_missing_context(self) -> None:
        fox, _ = make_fox(self.tmp)
        out = fox.chat("obscure question", mode="rag")
        self.assertFalse(out["grounded"])
        self.assertIn("could not find", out["answer"])

    def test_unrelated_query_filtered_by_min_score(self) -> None:
        fox, rag = make_fox(self.tmp)
        self._seed(fox, rag)
        # query with zero lexical overlap scores ~0 in the fake embedder
        out = fox.chat("quantum banana calculus", mode="rag")
        self.assertFalse(out["grounded"])  # nothing survived grounding filter

    def test_fallback_sources_when_no_citation_markers(self) -> None:
        llm = ScriptedLLM(["Answer without any markers at all."])
        fox, rag = make_fox(self.tmp, llm)
        self._seed(fox, rag)
        out = fox.chat("tell me about pheromone fields in swarm agents", mode="rag")
        # provenance must still be surfaced to the UI
        self.assertTrue(out["sources"])
        self.assertLessEqual(len(out["sources"]), 4)


class TestFoxModeBehaviors(TempDirTestCase):
    def test_thinking_mode_splits_reasoning(self) -> None:
        llm = ScriptedLLM([
            "Reasoning:\n1. look at swarm facts\n2. synthesize\n\nAnswer: They coordinate [1].",
        ])
        fox, rag = make_fox(self.tmp, llm)
        rag.index_paper("2401.42", "Swarm agents use pheromone trails. " * 20)
        out = fox.chat("swarm agents coordination?", mode="thinking")
        self.assertIn("pheromone facts" if False else "synthesize", out["thinking"])
        self.assertTrue(out["answer"].startswith("They coordinate"))

    def test_deep_thinking_decomposes_and_answers(self) -> None:
        llm = ScriptedLLM([])
        llm.extract_structured = mock.Mock(side_effect=[
            {"sub_questions": ["What is X?", "How does Y relate?"]},
            {"queries": []},
        ])
        answer = "Reasoning:\nsteps\n\nAnswer: Final deep answer."
        llm.answers.append(answer)
        fox, rag = make_fox(self.tmp, llm)
        rag.index_paper("2401.7", "Multi-agent debate improves reasoning quality. " * 20)
        out = fox.chat("multi agent debate X and Y?", mode="deep-thinking")
        self.assertEqual(out["sub_questions"], ["What is X?", "How does Y relate?"])
        self.assertTrue(out["answer"].startswith("Final deep"))

    def test_fast_mode_no_retrieval(self) -> None:
        llm = ScriptedLLM(["Quick take."])
        fox, _rag = make_fox(self.tmp, llm)
        out = fox.chat("hi fox", mode="fast")
        self.assertFalse(out["grounded"])
        self.assertEqual(out["sources"], [])
        self.assertEqual(llm.prompts[-1], "hi fox")

    def test_unknown_mode_falls_back_to_rag(self) -> None:
        fox, _ = make_fox(self.tmp)
        out = fox.chat("test", mode="bogus-mode")
        self.assertEqual(out["mode"], "rag")


class TestStatusIntent(unittest.TestCase):
    def test_detects_status_queries(self) -> None:
        for q in ("what's the ingestion status?", "any jobs running?", "show progress of papers"):
            self.assertTrue(looks_like_status_query(q), q)

    def test_normal_questions_not_flagged(self) -> None:
        self.assertFalse(looks_like_status_query("explain multi-agent alignment"))


class TestJobsRegistry(unittest.TestCase):
    def test_stage_lifecycle(self) -> None:
        reg = JobRegistry(history_max=5)
        job = reg.start("ingest", "arXiv 1234.5")
        reg.stage(job, "fetch", "done")
        with reg.ctx(job, "analyze"):
            pass
        reg.finish(job)
        data = job.to_dict()
        by_name = {s["name"]: s for s in data["stages"]}
        self.assertEqual(by_name["fetch"]["status"], "done")
        self.assertEqual(by_name["analyze"]["status"], "done")
        self.assertEqual(data["status"], "done")

    def test_error_marks_job_failed(self) -> None:
        reg = JobRegistry()
        job = reg.start("ingest", "x")
        try:
            with reg.ctx(job, "parse"):
                raise RuntimeError("pdf corrupt")
        except RuntimeError:
            pass
        self.assertEqual(job.status, "error")
        summary = reg.summary()
        self.assertEqual(summary["failed"], 1)

    def test_history_cap(self) -> None:
        reg = JobRegistry(history_max=3)
        for i in range(6):
            j = reg.start("ingest", f"job{i}")
            reg.finish(j)
        self.assertEqual(reg.summary()["total"], 3)

    def test_human_summary_format(self) -> None:
        reg = JobRegistry()
        job = reg.start("ingest", "arXiv 99")
        text = reg.human_summary()
        self.assertIn("arXiv 99", text)
        self.assertIn("running", text)
        reg.finish(job)


class TestConversations(TempDirTestCase):
    def test_persist_and_reload(self) -> None:
        fox, _ = make_fox(self.tmp)
        fox.chat("question one", mode="fast")
        cid = fox.list_conversations()[0]["id"]
        conv = fox.get_conversation(cid)
        roles = [m["role"] for m in conv["messages"]]
        self.assertEqual(roles, ["user", "assistant"])

    def test_clear_conversation(self) -> None:
        fox, _ = make_fox(self.tmp)
        fox.chat("q", mode="fast")
        cid = fox.list_conversations()[0]["id"]
        self.assertTrue(fox.clear_conversation(cid))
        self.assertIsNone(fox.get_conversation(cid))


class TestFeedbackStore(TempDirTestCase):
    def test_record_parse_summary(self) -> None:
        cfg = make_config(self.tmp)
        store = FeedbackStore(cfg)
        store.record(kind="fox", rating=2, comment="too vague", mode="rag")
        store.record(kind="fox", rating=5, comment="", mode="fast")
        s = store.summary(kind="fox")
        self.assertEqual(s["count"], 2)
        self.assertEqual(s["avg_rating"], 3.5)
        self.assertEqual(s["low_count"], 1)

    def test_prompt_hints_from_criticism(self) -> None:
        cfg = make_config(self.tmp)
        store = FeedbackStore(cfg)
        store.record(kind="fox", rating=1, comment="stop inventing numbers", mode="deep-research")
        hints = store.prompt_hints(mode="deep-research")
        self.assertTrue(any("inventing numbers" in h for h in hints))

    def test_rating_clamping(self) -> None:
        self.assertEqual(parse_rating("4"), 4)
        self.assertEqual(parse_rating(0), 1)
        self.assertEqual(parse_rating(99), 5)
        self.assertEqual(parse_rating(None), 0)


if __name__ == "__main__":
    unittest.main()
