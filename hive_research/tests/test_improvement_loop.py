from __future__ import annotations

import json
from unittest import mock

from hive_research.feedback import FeedbackStore
from hive_research.organizer import Organizer
from hive_research.tests.base import TempDirTestCase, make_config


def make_organizer(tmp) -> Organizer:
    cfg = make_config(tmp)
    org = Organizer.__new__(Organizer)
    org.config = cfg
    return org


class TestAutoImprovePass(TempDirTestCase):
    def test_no_feedback_reports_idle(self) -> None:
        org = make_organizer(self.tmp)
        out = org.auto_improve_pass()
        self.assertEqual(out["status"], "nothing-to-improve")

    def test_reanalyzes_low_rated_notes_with_hints(self) -> None:
        org = make_organizer(self.tmp)
        store = FeedbackStore(org.config)
        store.record(kind="notes", rating=1, paper_id="2401.1", comment="missed ablations")
        store.record(kind="fox", rating=1, comment="bad answer")  # fox kind ignored here

        node = mock.Mock()
        node.arxiv_id = "2401.1"
        node.label = "Paper One"
        org.kg = mock.Mock()
        org.kg.get_paper.return_value = node
        org._refresh_single = mock.Mock(return_value=True)

        out = org.auto_improve_pass()
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["improved_pass"][0]["status"], "improved")
        args, kwargs = org._refresh_single.call_args
        hints = kwargs.get("hints")
        self.assertTrue(hints and any("ablations" in h for h in hints))

    def test_respects_reanalyze_max(self) -> None:
        org = make_organizer(self.tmp)
        store = FeedbackStore(org.config)
        for i in range(6):
            store.record(kind="notes", rating=1, paper_id=f"2401.{i}", comment=f"bad {i}")
        org.kg = mock.Mock()
        org.kg.get_paper.side_effect = lambda pid: mock.Mock(arxiv_id=pid, label=pid)
        org._refresh_single = mock.Mock(return_value=True)
        out = org.auto_improve_pass()
        self.assertLessEqual(len(out["improved_pass"]), org.config.feedback_reanalyze_max)

    def test_unknown_paper_reported(self) -> None:
        org = make_organizer(self.tmp)
        store = FeedbackStore(org.config)
        store.record(kind="notes", rating=1, paper_id="9999.9", comment="")
        org.kg = mock.Mock()
        org.kg.get_paper.return_value = None
        out = org.auto_improve_pass()
        self.assertEqual(out["improved_pass"][0]["status"], "not-in-graph")

    def test_default_hint_when_comment_empty(self) -> None:
        org = make_organizer(self.tmp)
        store = FeedbackStore(org.config)
        store.record(kind="notes", rating=2, paper_id="2401.3", comment="")
        node = mock.Mock()
        node.arxiv_id = "2401.3"
        org.kg = mock.Mock()
        org.kg.get_paper.return_value = node
        org._refresh_single = mock.Mock(return_value=False)
        out = org.auto_improve_pass()
        args, kwargs = org._refresh_single.call_args
        self.assertTrue(kwargs.get("hints"))
        self.assertEqual(out["improved_pass"][0]["status"], "failed")


class TestFeedbackLoopIntegration(TempDirTestCase):
    def test_fox_hints_included_in_system_prompt(self) -> None:
        from hive_research.fox import Fox
        from hive_research.graph import KnowledgeGraph
        from hive_research.rag import RAGEngine
        from hive_research.tests.base import FakeLLM

        cfg = make_config(self.tmp)
        llm = FakeLLM()
        kg = KnowledgeGraph(cfg, graph_id="loop-test")
        rag = RAGEngine(cfg, llm, kg)
        fox = Fox(cfg, llm, kg, rag)
        fox.feedback.record(kind="fox", rating=1, mode="fast", comment="always cite dataset sizes")
        fox.chat("hello", mode="fast")  # no retrieval needed
        hints = fox._reinforcement_hints(mode="fast")
        self.assertIn("cite dataset sizes", hints)

    def test_hints_disabled_by_config(self) -> None:
        from hive_research.fox import Fox
        from hive_research.graph import KnowledgeGraph
        from hive_research.rag import RAGEngine
        from hive_research.tests.base import FakeLLM

        cfg = make_config(self.tmp)
        cfg.data["feedback"] = {"auto_improve": False}
        llm = FakeLLM()
        fox = Fox(cfg, llm, KnowledgeGraph(cfg, graph_id="loop2"), RAGEngine(cfg, llm, KnowledgeGraph(cfg, graph_id="loop2")))
        fox.feedback.record(kind="fox", rating=1, mode="rag", comment="x")
        self.assertEqual(fox._reinforcement_hints(), "")


if __name__ == "__main__":
    unittest.main()
