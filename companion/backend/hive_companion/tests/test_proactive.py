from __future__ import annotations

import asyncio
import unittest

from hive_companion.proactive import ProactiveEngine, SuggestionStore
from hive_companion.hive_client import HiveApiError
from hive_companion.events import EventBus
from hive_companion.policy import ReinforcementPolicy

from hive_companion.tests.base import TempDirTestCase


class FakeHive:
    """HiveClient double returning canned payloads per method."""

    def __init__(self) -> None:
        self.stats_payload = {"papers": 12, "notes": 12}
        self.feedback_payload: dict = {}
        self.pool_topics_payload: dict = {"topics": ["graph nets"]}
        self.digest_payload = {"total_new": 0}
        self.fail = False

    def _maybe_fail(self) -> None:
        if self.fail:
            raise HiveApiError("/api/x", 500, "boom")

    async def stats(self):
        self._maybe_fail()
        return self.stats_payload

    async def feedback_summary(self):
        self._maybe_fail()
        return self.feedback_payload

    async def pool_topics(self):
        self._maybe_fail()
        return self.pool_topics_payload

    async def digest(self):
        self._maybe_fail()
        return self.digest_payload

    async def get(self, path, **params):
        self._maybe_fail()
        if path == "/api/graph/clusters":
            return {"clusters": [{"label": "t1", "size": 5}, {"label": "t2", "size": 5}]}
        return {}


class TestSuggestions(TempDirTestCase):
    def test_dedupe_by_key(self) -> None:
        store = SuggestionStore(self.data_dir)
        first = store.upsert("a:b", {"kind": "digest", "title": "t"})
        second = store.upsert("a:b", {"kind": "digest", "title": "t again"})
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(len(store.open()), 1)

    def test_decide_moves_state(self) -> None:
        store = SuggestionStore(self.data_dir)
        item = store.upsert("k", {"kind": "improve", "title": "t"})
        assert item is not None
        decided = store.decide(item["id"], accepted=False)
        self.assertEqual(decided["status"], "rejected")
        self.assertEqual(store.open(), [])


class TestProactiveEngine(TempDirTestCase):
    def _engine(self, fake: FakeHive) -> ProactiveEngine:
        return ProactiveEngine(
            fake,
            SuggestionStore(self.data_dir),
            ReinforcementPolicy(self.data_dir / "p"),
            EventBus(),
        )

    def test_unanalyzed_papers_signal(self) -> None:
        fake = FakeHive()
        fake.stats_payload = {"papers": 30, "notes": 10}
        engine = self._engine(fake)
        created = asyncio.run(engine.run_cycle())
        kinds = [c["kind"] for c in created]
        self.assertIn("notes_refresh", kinds)

    def test_low_feedback_triggers_improve_suggestion(self) -> None:
        fake = FakeHive()
        fake.stats_payload = {"papers": 5, "notes": 5}
        fake.feedback_payload = {"count": 10, "low_count": 4}
        engine = self._engine(fake)
        created = asyncio.run(engine.run_cycle())
        improve = [c for c in created if c["kind"] == "improve"]
        self.assertTrue(improve)
        self.assertGreater(improve[0]["score"], 0)

    def test_no_duplicates_on_second_cycle(self) -> None:
        fake = FakeHive()
        fake.stats_payload = {"papers": 20, "notes": 5}
        engine = self._engine(fake)
        first = asyncio.run(engine.run_cycle())
        second = asyncio.run(engine.run_cycle())
        self.assertTrue(first)
        self.assertEqual(second, [])

    def test_hive_failure_yields_empty(self) -> None:
        fake = FakeHive()
        fake.fail = True
        engine = self._engine(fake)
        created = asyncio.run(engine.run_cycle())
        self.assertEqual(created, [])

    def test_policy_demotion_lowers_score(self) -> None:
        fake = FakeHive()
        fake.stats_payload = {"papers": 20, "notes": 5}
        policy = ReinforcementPolicy(self.data_dir / "p")
        for _ in range(8):
            policy.observe("suggestion:notes_refresh", False)
        engine = ProactiveEngine(
            fake,
            SuggestionStore(self.data_dir),
            policy,
            EventBus(),
        )
        created = asyncio.run(engine.run_cycle())
        refresh = [c for c in created if c["kind"] == "notes_refresh"]
        self.assertTrue(refresh)
        self.assertLess(refresh[0]["score"], 1.0)


if __name__ == "__main__":
    unittest.main()
