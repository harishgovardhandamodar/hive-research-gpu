from __future__ import annotations

import unittest

from hive_companion.episodic import EpisodeStore
from hive_companion.timeline import build_timeline

from hive_companion.tests.base import TempDirTestCase


class TestTimeline(TempDirTestCase):
    def _seed(self) -> EpisodeStore:
        store = EpisodeStore(self.data_dir)
        goal = store.append("goal", "study agent security", goal_id="")
        gid = goal["id"]
        # plan/step/feedback/observation filed under the goal id
        store.append("plan", "plan p1 started for goal: study agent security", goal_id=gid, plan_id="p1")
        store.append("step", "library.search -> ok", goal_id=gid, plan_id="p1", tool="library.search", status="done")
        store.append("step", "survey.start -> ok", goal_id=gid, plan_id="p1", tool="survey.start", status="done")
        store.append("feedback", "approved survey.start: go ahead", goal_id=gid)
        store.append("observation", "plan p1 finished: status=done, failures=0/2", goal_id=gid, plan_id="p1")
        # a conversation with no goal
        store.append("conversation", "Q: hi A: hello", session_id="s1")
        return store

    def test_threads_grouped_by_goal(self) -> None:
        timeline = build_timeline(self._seed())
        self.assertEqual(timeline["total_threads"], 1)
        thread = timeline["threads"][0]
        self.assertEqual(thread["goal"], "study agent security")
        self.assertEqual(thread["status"], "done")
        self.assertEqual([s["tool"] for s in thread["steps"]], ["library.search", "survey.start"])
        self.assertEqual(thread["steps_ok"], 2)
        self.assertEqual(len(thread["decisions"]), 1)

    def test_unfiled_episodes_listed(self) -> None:
        timeline = build_timeline(self._seed())
        kinds = [e["kind"] for e in timeline["unfiled"]]
        self.assertIn("conversation", kinds)

    def test_failed_status_detected(self) -> None:
        store = self._seed()
        goal = store.recent(kind="goal")[0]
        store.append("step", "rag.query -> error", goal_id=goal["id"], tool="rag.query", status="failed")
        store.append("observation", "plan p1 finished: status=failed, failures=1/3", goal_id=goal["id"])
        thread = build_timeline(store)["threads"][0]
        self.assertEqual(thread["status"], "failed")
        self.assertEqual(thread["steps_failed"], 1)

    def test_orphan_steps_get_synthetic_thread(self) -> None:
        store = self._seed()
        store.append("step", "orphan step -> ok", goal_id="ghost", tool="x", status="done")
        timeline = build_timeline(store)
        self.assertEqual(timeline["total_threads"], 2)
        ghost = next(t for t in timeline["threads"] if t["goal_id"] == "ghost")
        self.assertIn("(goal ghost)", ghost["goal"])

    def test_newest_thread_first_and_span(self) -> None:
        store = EpisodeStore(self.data_dir)
        g1 = store.append("goal", "first goal")
        g2 = store.append("goal", "second goal")
        timeline = build_timeline(store)
        self.assertEqual(timeline["threads"][0]["goal_id"], g2["id"])
        self.assertEqual(timeline["threads"][0]["span_s"], 0)


if __name__ == "__main__":
    unittest.main()
