from __future__ import annotations

import asyncio
import unittest
from typing import Any

from hive_companion.autonomy import AutonomyMode, gate, resolve_mode
from hive_companion.episodic import EpisodeStore
from hive_companion.executor import ApprovalStore, PlanExecutor
from hive_companion.events import EventBus
from hive_companion.planner import Plan, Planner, Step, _validate_steps
from hive_companion.policy import ReinforcementPolicy
from hive_companion.tools import ToolRegistry

from hive_companion.tests.base import TempDirTestCase


class FakeRegistry:
    """Registry double: two read-only tools, one mutating."""

    def __init__(self) -> None:
        self.fail_tools: set[str] = set()

    async def execute(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name in self.fail_tools:
            return {"status": "error", "tool": name, "error": "boom"}
        return {"status": "ok", "tool": name, "result": {"echo": args}}

    def is_mutating(self, name: str) -> bool:
        return name == "mutate"

    def get(self, name: str):
        class T:
            pass

        if name in ("read", "mutate"):
            t = T()
            t.name = name
            t.args = {}
            t.mutates = name == "mutate"
            return t
        return None


class TestEpisodic(TempDirTestCase):
    def test_append_and_recent(self) -> None:
        store = EpisodeStore(self.data_dir)
        store.append("goal", "survey diffusion models", session_id="s1")
        store.append("step", "ran library.search", session_id="s1")
        recent = store.recent()
        self.assertEqual(len(recent), 2)
        self.assertEqual(recent[-1]["kind"], "step")

    def test_retrieval_ranks_keyword_matches(self) -> None:
        store = EpisodeStore(self.data_dir)
        store.append("goal", "write survey on diffusion models", goal_id="g1")
        store.append("step", "ingested transformer papers", goal_id="g2")
        hits = store.retrieve("diffusion survey", limit=5)
        self.assertTrue(hits)
        self.assertIn("diffusion", hits[0]["summary"])

    def test_session_summary(self) -> None:
        store = EpisodeStore(self.data_dir)
        store.append("goal", "goal one", session_id="s9")
        store.append("step", "step one", session_id="s9", status="failed")
        summary = store.summarize_session("s9")
        self.assertEqual(summary["count"], 2)
        self.assertEqual(summary["failures"], ["step one"])

    def test_context_for_prompt(self) -> None:
        store = EpisodeStore(self.data_dir)
        store.append("observation", "plan finished for topic quantum", goal_id="g1")
        context = store.context_for_prompt("quantum topic next steps")
        self.assertIn("quantum", context)


class TestAutonomy(unittest.TestCase):
    def test_gate_matrix(self) -> None:
        cases = [
            (AutonomyMode.APPROVE, False, "run"),
            (AutonomyMode.APPROVE, True, "wait_approval"),
            (AutonomyMode.TIERED, False, "run"),
            (AutonomyMode.TIERED, True, "wait_approval"),
            (AutonomyMode.AUTO, False, "run"),
            (AutonomyMode.AUTO, True, "run"),
        ]
        for mode, mutates, expected in cases:
            self.assertEqual(gate(mode, mutates), expected)

    def test_resolve_defaults_to_tiered(self) -> None:
        self.assertIs(resolve_mode(None), AutonomyMode.TIERED)
        self.assertIs(resolve_mode("auto"), AutonomyMode.AUTO)
        self.assertIs(resolve_mode("bogus"), AutonomyMode.TIERED)


class TestPolicy(TempDirTestCase):
    def test_weights_learn_from_outcomes(self) -> None:
        policy = ReinforcementPolicy(self.data_dir)
        for _ in range(6):
            policy.observe("suggestion:survey", True)
        for _ in range(4):
            policy.observe("suggestion:survey", False)
        weight = policy.weight("suggestion:survey")
        self.assertAlmostEqual(weight, round((6 + 2) / (10 + 4), 3))

    def test_unknown_signal_neutral(self) -> None:
        policy = ReinforcementPolicy(self.data_dir)
        self.assertEqual(policy.weight("tool:nope"), 0.5)

    def test_persistence_across_instances(self) -> None:
        policy = ReinforcementPolicy(self.data_dir)
        policy.observe("tool:add_paper", True)
        again = ReinforcementPolicy(self.data_dir)
        self.assertGreater(again.weight("tool:add_paper"), 0.5)

    def test_planner_hints_mention_failing_tools(self) -> None:
        policy = ReinforcementPolicy(self.data_dir)
        for _ in range(8):
            policy.observe("tool:rag.rebuild", False)
        hints = policy.planner_hints()
        self.assertIn("rag.rebuild", hints)

    def test_ranked_prefers_accepted(self) -> None:
        policy = ReinforcementPolicy(self.data_dir)
        for _ in range(5):
            policy.observe("suggestion:a", True)
            policy.observe("suggestion:b", False)
        ranked = policy.ranked(["suggestion:b", "suggestion:a"])
        self.assertEqual(ranked[0], "suggestion:a")


def _make_plan(steps: list[tuple[str, str]]) -> Plan:
    return Plan(
        id="p1",
        goal_id="g1",
        goal="test goal",
        steps=[Step(index=i, tool=tool, args={}, rationale=r) for i, (tool, r) in enumerate(steps)],
    )


class TestExecutor(TempDirTestCase):
    def _executor(self) -> tuple[PlanExecutor, FakeRegistry]:
        registry = FakeRegistry()
        bus = EventBus()
        executor = PlanExecutor(
            registry,
            EpisodeStore(self.data_dir),
            ReinforcementPolicy(self.data_dir),
            bus,
            ApprovalStore(self.data_dir),
            approval_timeout_s=0.05,
        )
        return executor, registry

    def _collect(self, executor: PlanExecutor, plan: Plan, mode: AutonomyMode) -> list[dict[str, Any]]:
        async def run() -> list[dict[str, Any]]:
            events = []
            async for event in executor.run_plan(plan, "g1", "s1", mode):
                events.append(event)
            return events

        return asyncio.run(run())

    def test_auto_runs_everything_without_approval(self) -> None:
        executor, _ = self._executor()
        plan = _make_plan([("read", "gather"), ("mutate", "apply")])
        events = self._collect(executor, plan, AutonomyMode.AUTO)
        kinds = [e["type"] for e in events]
        self.assertNotIn("awaiting_approval", kinds)
        self.assertEqual(kinds.count("step_finished"), 2)
        self.assertEqual(plan.steps[-1].state, "done")

    def test_approve_waits_and_skips_on_timeout(self) -> None:
        executor, _ = self._executor()
        plan = _make_plan([("read", "ok"), ("mutate", "needs approval")])
        events = self._collect(executor, plan, AutonomyMode.APPROVE)
        self.assertIn("awaiting_approval", [e["type"] for e in events])
        self.assertEqual(plan.steps[-1].state, "skipped")
        self.assertEqual(events[-1]["status"], "done")  # partial completion still finishes

    def test_tiered_auto_runs_readonly(self) -> None:
        executor, _ = self._executor()
        plan = _make_plan([("read", "safe")])
        events = self._collect(executor, plan, AutonomyMode.TIERED)
        self.assertNotIn("awaiting_approval", [e["type"] for e in events])
        self.assertEqual(plan.steps[0].state, "done")

    def test_failures_recorded(self) -> None:
        executor, registry = self._executor()
        registry.fail_tools.add("read")
        plan = _make_plan([("read", "will fail"), ("read", "fails too")])
        events = self._collect(executor, plan, AutonomyMode.AUTO)
        self.assertEqual(events[-1]["status"], "failed")
        self.assertEqual(plan.steps[0].state, "failed")

    def test_episodes_written_per_step(self) -> None:
        store = EpisodeStore(self.data_dir)
        registry = FakeRegistry()
        executor = PlanExecutor(
            registry,
            store,
            ReinforcementPolicy(self.data_dir / "x"),
            EventBus(),
            ApprovalStore(self.data_dir / "y"),
        )
        plan = _make_plan([("read", "one"), ("mutate", "two")])

        async def run() -> None:
            async for _event in executor.run_plan(plan, "g1", "s1", AutonomyMode.AUTO):
                pass

        asyncio.run(run())
        step_episodes = store.recent(kind="step")
        self.assertEqual(len(step_episodes), 2)


class TestApprovalStore(TempDirTestCase):
    def test_resolve_pending_flow(self) -> None:
        store = ApprovalStore(self.data_dir)
        item = store.create("p1", 0, "mutate", {}, "why not")
        resolved = store.resolve(item["id"], approved=True, note="go ahead")
        self.assertIsNotNone(resolved)
        self.assertTrue(asyncio.run(store.wait(item["id"], timeout_s=0.01)))
        self.assertIsNone(store.resolve(item["id"], approved=False))

    def test_wait_times_out(self) -> None:
        store = ApprovalStore(self.data_dir)
        item = store.create("p1", 0, "mutate", {}, "")
        self.assertFalse(asyncio.run(store.wait(item["id"], timeout_s=0.01)))


class TestPlanner(TempDirTestCase):
    def test_heuristic_survey_plan(self) -> None:
        planner = Planner(RealSpecRegistry(), None, ReinforcementPolicy(self.data_dir))

        async def run() -> Plan:
            return await planner.build("write a survey on graph neural networks")

        plan = asyncio.run(run())
        tools = [s.tool for s in plan.steps]
        self.assertIn("survey.start", tools)
        self.assertIn("library.search", tools)

    def test_heuristic_improve_plan(self) -> None:
        planner = Planner(RealSpecRegistry(), None, ReinforcementPolicy(self.data_dir))

        async def run() -> Plan:
            return await planner.build("improve the notes the reviewer hated")

        plan = asyncio.run(run())
        tools = [s.tool for s in plan.steps]
        self.assertIn("improve.run", tools)

    def test_validation_drops_unknown_tools(self) -> None:
        steps, dropped = _validate_steps(
            [
                {"tool": "library.stats"},
                {"tool": "does.not.exist"},
                {"tool": "library.search", "args": {"query": "x"}},
                {"tool": "library.search"},  # missing required arg
            ],
            _SpecRegistry(),
        )
        self.assertEqual([s.tool for s in steps], ["library.stats", "library.search"])
        self.assertTrue(any("does.not.exist" in d for d in dropped))
        self.assertTrue(any("missing" in d for d in dropped))


class _SpecRegistry:
    """Duck-typed registry exposing only what _validate_steps needs."""

    def get(self, name: str):
        if name == "library.stats":
            return SimpleTool(name, args={})
        if name == "library.search":
            return SimpleTool(name, args={"query": "keyword query"})
        return None


class RealSpecRegistry:
    """Duck-typed registry with the real tool names/args, no network."""

    def __init__(self) -> None:
        self._names = {
            "library.search": {"query": "q"},
            "survey.start": {"topic": "t"},
            "digest.daily": {},
            "improve.run": {},
            "feedback.summary": {},
            "library.import_query": {"query": "q", "model": "m"},
            "rag.rebuild": {},
            "library.stats": {},
            "graph.clusters": {},
            "graph.similarity": {"paper_ids": "ids"},
            "pool.topics": {},
            "pool.import_topic": {"topic": "t", "max_results": "n"},
            "rag.query": {"question": "q"},
            "fox.chat": {"message": "m", "mode": "mode"},
        }

    def get(self, name: str):
        if name not in self._names:
            return None
        tool = SimpleTool(name, args=self._names[name])
        tool.mutates = name in {"survey.start", "library.import_query", "improve.run",
                                 "rag.rebuild", "pool.import_topic"}
        return tool


class SimpleTool:
    def __init__(self, name: str, args: dict[str, str]) -> None:
        self.name = name
        self.args = args
        self.mutates = False


if __name__ == "__main__":
    unittest.main()
