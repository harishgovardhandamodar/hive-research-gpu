from __future__ import annotations

import unittest
from datetime import datetime, timezone

from hive_companion.cite import bibtex, topic_drift
from hive_companion.schedules import is_due


class TestScheduleDue(unittest.TestCase):
    def test_due_matrix(self) -> None:
        monday = datetime(2026, 8, 24, 10, 0, tzinfo=timezone.utc)
        tuesday = datetime(2026, 8, 25, 10, 0, tzinfo=timezone.utc)

        daily_enabled = {"cadence": "daily", "enabled": True, "last_run": None}
        self.assertTrue(is_due(daily_enabled, monday))

        ran_recently = dict(daily_enabled, last_run=monday.isoformat())
        self.assertFalse(is_due(ran_recently, monday))
        self.assertTrue(is_due(ran_recently, tuesday))

        weekly_mon = {"cadence": "weekly", "weekday": 0, "enabled": True, "last_run": None}
        self.assertFalse(is_due(weekly_mon, tuesday))  # wrong weekday
        self.assertTrue(is_due(weekly_mon, monday))

        disabled = dict(daily_enabled, enabled=False)
        self.assertFalse(is_due(disabled, monday))


class TestBibtex(unittest.TestCase):
    def test_basic_fields_and_key(self) -> None:
        out = bibtex(
            "2202.09061v4",
            "VLP: A Survey {on} Vision-Language",
            "Feilong Chen, Duzhen Zhang",
            "2022-02-18",
        )
        self.assertIn("@article{chen2022220209061,", out)
        self.assertIn("author = {Feilong Chen and Duzhen Zhang},", out)
        self.assertIn("eprint = {2202.09061v4}", out)
        self.assertIn("year = {2022},", out)
        self.assertNotIn("{on}", out)


class TestTopicDrift(unittest.TestCase):
    def test_detects_rising_above_threshold(self) -> None:
        drift = topic_drift({"a": 0.6, "b": 0.4}, {"a": 0.4, "b": 0.6})
        self.assertEqual(drift[0]["topic"], "a")
        self.assertEqual(drift[0]["direction"], "rising")

    def test_quiet_when_stable(self) -> None:
        self.assertEqual(topic_drift({"a": 0.51}, {"a": 0.50}), [])


if __name__ == "__main__":
    unittest.main()
