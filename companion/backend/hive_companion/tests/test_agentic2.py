from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hive_companion.plan_templates import TemplateStore
from hive_companion.policy import ReinforcementPolicy


class TestEarnedAutonomy(unittest.TestCase):
    def test_trust_requires_sample_and_rate(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            policy = ReinforcementPolicy(Path(d))
            for _ in range(3):
                policy.observe("tool:library.add_paper", True)
            self.assertFalse(policy.trust("library.add_paper"))  # only 3 samples
            for _ in range(3):
                policy.observe("tool:library.add_paper", True)
            self.assertTrue(policy.trust("library.add_paper"))  # 6/6 >= 90%
            policy.observe("tool:library.add_paper", False)
            self.assertFalse(policy.trust("library.add_paper"))  # 6/7 < 90%

    def test_tool_stats_feed_hints(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            policy = ReinforcementPolicy(Path(d))
            for _ in range(5):
                policy.observe("tool:fox.chat", True)
            hints = policy.planner_hints()
            self.assertIn("fox.chat", hints)
            self.assertIn("5 runs", hints)


class TestTemplateStore(unittest.TestCase):
    def test_save_upsert_and_delete(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            store = TemplateStore(Path(d))
            steps = [{"tool": "library.stats", "args": {}}]
            first = store.save("survey agent security", steps, "llm")
            again = store.save("Survey Agent Security", steps, "llm")  # same shape
            self.assertEqual(first["id"], again["id"])  # upsert by goal shape
            self.assertEqual(again["uses"], 2)
            self.assertEqual(len(store.items()), 1)
            self.assertTrue(store.delete(first["id"]))
            self.assertFalse(store.delete(first["id"]))


if __name__ == "__main__":
    unittest.main()
