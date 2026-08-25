from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from hive_companion.cite import _key, bibtex
from hive_companion.episodic import EpisodeStore


class TestEpisodeStoreBounded(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = EpisodeStore(Path(self.tmp.name))
        self.store.MAX_EPISODES = 10

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_tail_cache_serves_reads_without_rereading(self) -> None:
        self.store.append("goal", "first goal")
        first = self.store._load()
        # simulate a second process appending behind our back — cache hides it
        with open(self.store.path, "a") as f:
            f.write(json.dumps({"id": "x", "ts": "t", "kind": "note", "summary": "s"}) + "\n")
        self.assertEqual(len(self.store._load()), len(first))

    def test_append_updates_cache(self) -> None:
        self.store.append("goal", "a")
        self.store.append("step", "b")
        self.assertEqual([e["kind"] for e in self.store.recent(limit=10)], ["goal", "step"])

    def test_compaction_caps_file(self) -> None:
        for i in range(25):
            self.store.append("obs", f"event {i}")
        fresh = EpisodeStore(Path(self.tmp.name))
        fresh.MAX_EPISODES = 10
        episodes = fresh._load()
        self.assertLessEqual(len(episodes), 10)
        self.assertEqual(episodes[-1]["summary"], "event 24")  # newest kept


class TestRetrieveRecency(unittest.TestCase):
    def test_recent_episode_wins_on_equal_overlap(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        try:
            store = EpisodeStore(Path(tmp.name))
            old = store.append("observation", "survey on agent security completed")
            new = store.append("observation", "survey on agent security started")
            # backdate the first episode in both cache and file
            old["ts"] = "2020-01-01T00:00:00+00:00"
            path = Path(tmp.name, "episodes.jsonl")
            lines = []
            for ep in path.read_text().splitlines():
                data = json.loads(ep)
                if data["id"] == old["id"]:
                    data["ts"] = old["ts"]
                lines.append(json.dumps(data))
            path.write_text("\n".join(lines) + "\n")
            hits = store.retrieve("agent security survey", limit=2)
            self.assertEqual(hits[0]["id"], new["id"])
        finally:
            tmp.cleanup()


class TestCiteKey(unittest.TestCase):
    def test_key_is_alphanumeric(self) -> None:
        key = _key("2401.12345v2", "Jane Doe", "n.d.")
        self.assertTrue(key.isalnum())
        self.assertIn("nd", key)

    def test_bibtex_renders(self) -> None:
        text = bibtex("2401.12345", "A Title", "J Doe", "2024")
        self.assertTrue(text.startswith("@article{"))
        self.assertIn("eprint = {2401.12345}", text)


if __name__ == "__main__":
    unittest.main()
