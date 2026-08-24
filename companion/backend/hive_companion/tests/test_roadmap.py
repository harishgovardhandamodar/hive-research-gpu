from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone

from hive_companion.tests.base import TempDirTestCase
from hive_companion.cite import bibtex, topic_drift
from hive_companion.schedules import is_due
from hive_companion.tests.base import TempDirTestCase


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


class TestBackupSnapshots(TempDirTestCase):
    def test_snapshot_prune_and_restore_list(self) -> None:
        import tarfile
        from pathlib import Path

        from hive_companion.backup import create_snapshot, list_snapshots, load_runs

        data = Path(self.data_dir) / "stores"
        data.mkdir(parents=True)

        (data / "episodes.jsonl").write_text('{"a": 1}\n{"a": 2}\n')
        (data / "policy.json").write_text('{"weights": {}}')

        arc1 = create_snapshot(data, keep=2, stamp="20260824_010101")
        arc2 = create_snapshot(data, keep=2, stamp="20260824_020202")
        arc3 = create_snapshot(data, keep=2, stamp="20260824_030303")

        self.assertIsNotNone(arc1 and arc2 and arc3)
        names = [s["file"] for s in list_snapshots(data)]
        # newest first, pruned to keep=2
        self.assertEqual(len(names), 2)
        self.assertEqual(names[0], "agentdata_20260824_030303.tar.gz")

        with tarfile.open(arc3) as tar:
            members = sorted(m.name for m in tar.getmembers())
        self.assertEqual(members, ["episodes.jsonl", "policy.json"])

    def test_load_runs_repairs_interrupted(self) -> None:
        from pathlib import Path

        from hive_companion.ideagent import IdeaRun
        from hive_companion.backup import load_runs

        path = Path(self.data_dir) / "ideas.jsonl"
        done = {
            "id": "r1", "topic": "t", "status": "done", "iterations": 4,
            "archive_cells": 12, "cells_filled": 2, "candidates_seen": 4,
            "ideas": [{"title": "x", "overall": 0.7, "cell": "empirical/bridging"}],
        }
        stuck = dict(done, id="r2", status="running")
        path.write_text(json.dumps(done) + "\n" + json.dumps(stuck) + "\n")

        runs = load_runs(path, IdeaRun.from_dict)
        statuses = {r.id: r.status for r in runs}
        self.assertEqual(statuses["r1"], "done")
        self.assertEqual(statuses["r2"], "interrupted")
