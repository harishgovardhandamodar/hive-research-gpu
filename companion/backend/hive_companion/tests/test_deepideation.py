from __future__ import annotations

import asyncio
import json
import unittest

from hive_companion.deepideation import ConceptNetwork, DeepIdeationEngine, DeepRun
from hive_companion.kg import KGCache


def _kg() -> KGCache:
    kg = KGCache.__new__(KGCache)
    kg.client = None
    kg._graph = {
        "nodes": [
            {"id": "c1", "label": "prompt injection", "type": "concept",
             "definition": "adversarial inputs that hijack agent instructions"},
            {"id": "c2", "label": "information flow audit", "type": "concept"},
            {"id": "c3", "label": "multi agent delegation", "type": "concept"},
            {"id": "p1", "label": "Paper One", "type": "paper", "title": "Paper One"},
            {"id": "p2", "label": "Paper Two", "type": "paper", "title": "Paper Two"},
        ],
        "links": [
            {"source": "c1", "target": "p1", "relation": "related_to"},
            {"source": "c1", "target": "p2", "relation": "related_to"},
            {"source": "c2", "target": "p1", "relation": "related_to"},
            {"source": "c3", "target": "p2", "relation": "related_to"},
        ],
    }
    kg._loaded_at = 9e9
    return kg


class ScriptedLLM:
    """Returns scripted responses in order; records calls."""

    def __init__(self, script: list[str]) -> None:
        self.script = list(script)
        self.calls: list[str] = []

    async def chat(self, system: str, user: str, json_mode: bool = False,
                   num_predict: int = 1024, temperature: float = 0.2) -> str:
        marker = "foundational" if "deepest shared" in system else (
            "under-explored" if "under-explored direction" in system else (
                "novelty auditor" if "novelty auditor" in system else (
                    "creative research-idea engine" if "research-idea engine" in system else "reviewer"
                )
            )
        )
        self.calls.append(marker)
        if not self.script:
            raise RuntimeError("script dry")
        return self.script.pop(0)


def _network() -> ConceptNetwork:
    net = ConceptNetwork(_kg())
    assert net.refresh(force=True), "network build failed"
    return net


class TestConceptNetwork(unittest.TestCase):
    def test_cooccurrence_built(self) -> None:
        net = _network()
        nbrs = net.neighbours.get("c1", {})
        self.assertIn("c2", nbrs)
        self.assertEqual(nbrs["c2"], 1)  # share p1

    def test_seeds_rank_by_topic_overlap(self) -> None:
        net = _network()
        seeds = net.seeds_for("prompt injection security")
        self.assertEqual(seeds[0], "c1")

    def test_bridge_excludes_used(self) -> None:
        net = _network()
        bridge = net.bridge_for("c1", used={"c2"})
        self.assertEqual(bridge, "c3")


class TestDeepRun(unittest.TestCase):
    def test_pair_explored_with_refinement_chain(self) -> None:
        script = [
            '{"principle":"least privilege"}',                     # backward
            '{"dir":"continuous auditing"}',                        # forward
            json.dumps({"title": "Draft Idea", "summary": "s",
                        "mechanism": "audit trails", "builds_on": ["c1", "c2"]}),
            json.dumps({"critique": "too close to prior work",
                        "revised_title": "Revised Idea",
                        "revised_summary": "sharper s"}),
            json.dumps({"novelty": 8, "feasibility": 6, "impact": 7, "verdict": "solid"}),
            # second pair (c3 bridge)
            '{"principle":"delegation bounds"}',
            '{"dir":"policy learning"}',
            json.dumps({"title": "Second Idea", "summary": "s2", "mechanism": "m2"}),
            json.dumps({"critique": "ok", "revised_title": "Second Idea",
                        "revised_summary": "s2"}),
            json.dumps({"novelty": 5, "feasibility": 7, "impact": 6}),
        ]
        llm = ScriptedLLM(script)
        searches = {"n": 0}

        async def fake_search(q: str):
            searches["n"] += 1
            return [{"title": "Similar Existing Work"}]

        engine = DeepIdeationEngine(
            llm_fast=llm, llm_main=None, kg=_kg(), network=_network(),
            search_fn=fake_search,
        )

        async def main():
            run = await engine.run("prompt injection and information flow", iterations=2, depth=2, wait=True)
            return run

        run = asyncio.run(main())
        self.assertEqual(run.status, "done")
        self.assertEqual(len(run.ideas), 2)
        first = next(i for i in run.ideas if i["title"] == "Revised Idea")
        self.assertEqual(first["revisions"], 2)
        self.assertEqual(first["chain"], ["prompt injection", "information flow audit"])
        self.assertGreater(searches["n"], 0, "novelty check should query the library")
        ranked = run.to_dict()["ideas"]
        self.assertEqual(ranked[0]["overall"], max(i["overall"] for i in run.ideas))

    def test_on_complete_called(self) -> None:
        completed = []
        llm = ScriptedLLM([
            '{"p":"x"}', '{"d":"y"}',
            json.dumps({"title": "T", "summary": "s", "mechanism": "m"}),
            json.dumps({"novelty": 4, "feasibility": 9, "impact": 5}),
        ])
        engine = DeepIdeationEngine(
            llm_fast=llm, llm_main=None, kg=_kg(), network=_network(),
            on_complete=lambda r: completed.append(r.id),
        )

        async def main():
            await engine.run("t", iterations=1, depth=0, wait=True)

        asyncio.run(main())
        self.assertEqual(completed, [engine.history[-1].id])


if __name__ == "__main__":
    unittest.main()
