from __future__ import annotations

import asyncio
import unittest

from hive_companion.executor import PlanExecutor
from hive_companion.ideagent import IdeagentEngine, IdeaRun
from hive_companion.planner import Plan, Step
from hive_companion.tools import ToolRegistry

from .test_agent import _make_plan  # reuse the existing fixtures


class _FakeRegistry:
    """Minimal registry double: records concurrency + mutation counts."""

    def __init__(self) -> None:
        self.active = 0
        self.max_concurrency = 0
        self.calls: list[str] = []

    def is_mutating(self, name: str) -> bool:
        return name.startswith("mut")

    async def execute(self, name: str, args: dict) -> dict:
        self.calls.append(name)
        self.active += 1
        self.max_concurrency = max(self.max_concurrency, self.active)
        await asyncio.sleep(0.01)
        self.active -= 1
        return {"status": "ok", "result": {"tool": name}}


class _SilentStore:
    def append(self, *a, **k):
        return {"id": "e"}

    def recent(self, *a, **k):
        return []


class _NoPolicy:
    def observe(self, *a, **k):
        return None


class _NoBus:
    def publish(self, *a, **k):
        return None


def _executor(registry: _FakeRegistry, max_mutations: int = 6) -> PlanExecutor:
    return PlanExecutor(
        registry,
        _SilentStore(),  # type: ignore[arg-type]
        _NoPolicy(),  # type: ignore[arg-type]
        _NoBus(),  # type: ignore[arg-type]
        approvals=None,  # type: ignore[arg-type]  (auto mode never gates)
        max_mutations=max_mutations,
        budget_s=3600,
    )


def _collect(executor: PlanExecutor, plan: Plan) -> dict:
    async def go() -> dict:
        last = {}
        async for ev in executor.run_plan(plan, "g", "s", __import__("hive_companion.autonomy", fromlist=["AutonomyMode"]).AutonomyMode.AUTO):
            if ev.get("type") == "plan_finished":
                last = ev
        return last

    return asyncio.run(go())


class TestParallelReadOnly(unittest.TestCase):
    def test_read_only_steps_run_concurrently(self) -> None:
        registry = _FakeRegistry()
        executor = _executor(registry)
        plan = _make_plan([("read", "a"), ("read", "b"), ("read", "c")])
        final = _collect(executor, plan)
        self.assertGreaterEqual(registry.max_concurrency, 2)  # batched, not serial
        self.assertEqual(final["status"], "done")

    def test_mutating_step_runs_alone(self) -> None:
        registry = _FakeRegistry()
        executor = _executor(registry)
        plan = _make_plan([("read", "a"), ("mut.write", "b"), ("read", "c")])
        _collect(executor, plan)
        self.assertEqual(registry.max_concurrency, 1)  # mutators never batch


class TestMutationBudget(unittest.TestCase):
    def test_excess_mutations_are_skipped(self) -> None:
        registry = _FakeRegistry()
        executor = _executor(registry, max_mutations=1)
        plan = _make_plan([("mut.w1", "1"), ("mut.w2", "2"), ("mut.w3", "3")])
        final = _collect(executor, plan)
        skipped = [s for s in plan.steps if s.state == "skipped"]
        done = [s for s in plan.steps if s.state == "done"]
        self.assertEqual(len(done), 1)
        self.assertEqual(len(skipped), 2)
        self.assertEqual(final["steps"], 3)


class TestIdeaNoveltyDedup(unittest.TestCase):
    def _engine_with_history(self, titles: list[str]) -> IdeagentEngine:
        engine = IdeagentEngine(llm_fast=None, llm_main=None, kg=object())  # type: ignore[arg-type]
        past = IdeaRun("t", 1)
        for t in titles:
            past.archive[("approach", "risk")] = {"title": t}
            past.candidates.append({"title": t})
        engine.history.append(past)
        return engine

    def test_same_idea_across_runs_is_duplicate(self) -> None:
        engine = self._engine_with_history(["Agentic security assessment framework for enterprise AI"])
        self.assertTrue(engine._is_duplicate("agentic security assessment framework for enterprise ai"))

    def test_distinct_idea_passes(self) -> None:
        engine = self._engine_with_history(["Federated learning privacy budgets"])
        self.assertFalse(engine._is_duplicate("Zero trust architecture for autonomous agents"))

    def test_current_run_excluded_from_self_comparison(self) -> None:
        run = IdeaRun("t", 1)
        engine = IdeagentEngine(llm_fast=None, llm_main=None, kg=object())  # type: ignore[arg-type]
        engine.history.append(run)
        self.assertFalse(engine._is_duplicate("anything at all", exclude=run))


if __name__ == "__main__":
    unittest.main()
