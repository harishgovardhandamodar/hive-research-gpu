from __future__ import annotations

import asyncio
import json
import unittest

from hive_companion.ideagent import (
    IdeagentEngine,
    IdeaRun,
    _bucket,
    _parse_json,
    overall,
)
from hive_companion.kg import KGCache


class FakeLLM:
    """Rotates through canned JSON responses."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    async def chat(self, system: str, user: str, json_mode: bool = False, num_predict: int = 1024) -> str:
        self.calls.append((system[:20], user[:40]))
        if not self.responses:
            raise RuntimeError("dry")
        return self.responses.pop(0)


def _kg() -> KGCache:
    kg = KGCache.__new__(KGCache)
    kg.client = None
    kg._graph = {
        "nodes": [
            {"id": "c1", "label": "ai agent security", "type": "concept"},
            {"id": "c2", "label": "prompt injection", "type": "concept"},
            {"id": "p1", "label": "Some Agent Paper", "type": "paper"},
        ],
        "links": [],
    }
    kg._loaded_at = 9e9
    return kg


class TestBuckets(unittest.TestCase):
    def test_keyword_match_and_hash_fallback(self) -> None:
        self.assertEqual(_bucket("an empirical study", ["theoretical", "empirical"]), "empirical")
        self.assertEqual(_bucket("radical redesign", ["incremental", "bridging", "radical"]), "radical")
        # unknown text still lands in a valid bucket
        self.assertIn(_bucket("zzz", ["a", "b"]), ["a", "b"])

    def test_parse_json_extracts_object(self) -> None:
        data = _parse_json('noise before {"title": "T"} noise after')
        self.assertEqual(data["title"], "T")

    def test_overall_weighting(self) -> None:
        # novelty dominates
        self.assertEqual(overall(10, 0, 0), 0.5)
        self.assertEqual(overall(0, 10, 10), 0.5)
        self.assertEqual(overall(8, 8, 8), 0.8)


class TestArchive(unittest.TestCase):
    def test_best_per_cell_kept(self) -> None:
        run = IdeaRun("topic", 4)

        class L:
            pass

        engine = IdeagentEngine.__new__(IdeagentEngine)
        engine.bus = None

        idea_a = {"title": "weak", "approach": "empirical", "risk": "bridging",
                  "overall": 0.4, "novelty": 4, "feasibility": 4, "impact": 4}
        idea_b = {"title": "strong same cell", "approach": "empirical", "risk": "bridging",
                  "overall": 0.9, "novelty": 9, "feasibility": 9, "impact": 9}
        idea_c = {"title": "other cell", "approach": "tooling", "risk": "radical",
                  "overall": 0.5, "novelty": 5, "feasibility": 5, "impact": 5}

        engine._archive(run, idea_a, 0)
        engine._archive(run, idea_b, 1)
        engine._archive(run, idea_c, 2)

        self.assertEqual(len(run.archive), 2)
        ranked = run.rank()
        self.assertEqual(ranked[0]["title"], "strong same cell")

    def test_run_records_events(self) -> None:
        run = IdeaRun("t", 3)
        engine = IdeagentEngine.__new__(IdeagentEngine)
        engine.bus = None
        engine._archive(run, {"title": "x", "approach": "systems", "risk": "radical",
                              "overall": 0.6}, 0)
        self.assertTrue(run.events[0]["kept"])


class TestEngineRun(unittest.TestCase):
    def test_full_mini_run(self) -> None:
        gen1 = json.dumps({
            "title": "Idea A", "summary": "s", "approach": "empirical",
            "risk": "bridging", "novelty": 7, "feasibility": 6, "impact": 7,
            "builds_on": ["ai agent security"],
        })
        judge1 = json.dumps({"novelty": 8, "feasibility": 6, "impact": 7, "verdict": "ok"})
        gen2 = json.dumps({
            "title": "Idea B", "summary": "s2", "approach": "tooling",
            "risk": "radical", "novelty": 6, "feasibility": 5, "impact": 6,
        })
        judge2 = json.dumps({"novelty": 5, "feasibility": 5, "impact": 5})
        llm = FakeLLM([gen1, judge1, gen2, judge2])
        engine = IdeagentEngine(llm_fast=llm, llm_main=None, kg=_kg())

        run = asyncio.run(engine.run("AI agent security research", iterations=2, model="fast", wait=True))
        self.assertEqual(run.status, "done")
        self.assertEqual(len(run.candidates), 2)
        self.assertEqual(run.cells_filled(), 2)
        titles = [i["title"] for i in run.rank()]
        self.assertIn("Idea A", titles)
        self.assertIn("Idea B", titles)
        top = run.rank()[0]
        self.assertEqual(top["title"], "Idea A")  # higher overall
        self.assertTrue(all(i["overall"] >= 0.3 for i in run.rank()))

    def test_second_run_accepted_after_previous_completes(self) -> None:
        llm = FakeLLM([])  # every call raises → iterations survive as failures
        engine = IdeagentEngine(llm_fast=llm, llm_main=None, kg=_kg())
        run = asyncio.run(engine.run("t", iterations=2, wait=True))
        self.assertEqual(run.status, "done")  # resilient: failures logged, run completes
        self.assertEqual(len(run.candidates), 0)
        # active slot released
        run2 = asyncio.run(engine.run("t2", iterations=2, wait=True))
        self.assertEqual(run2.status, "done")


if __name__ == "__main__":
    unittest.main()
