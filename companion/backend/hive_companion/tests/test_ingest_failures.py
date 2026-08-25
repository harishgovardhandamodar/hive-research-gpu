from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hive_companion.ingest_failures import IngestFailureStore, inner_add_status


class TestIngestFailureStore(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = IngestFailureStore(Path(self.tmp.name))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_record_and_clear(self) -> None:
        self.assertEqual(self.store.count(), 0)
        entry = self.store.record_failure("2401.1v1", title="T", error="boom")
        self.assertEqual(entry["attempts"], 1)
        self.assertEqual(self.store.count(), 1)
        again = self.store.record_failure("2401.1v1", error="boom again")
        self.assertEqual(again["attempts"], 2)
        self.store.record_success("2401.1v1")
        self.assertEqual(self.store.count(), 0)

    def test_persistence(self) -> None:
        self.store.record_failure("2401.2v1", error="x")
        reloaded = IngestFailureStore(Path(self.tmp.name))
        self.assertEqual(reloaded.count(), 1)
        self.assertEqual(reloaded.items()[0]["arxiv_id"], "2401.2v1")

    def test_items_sorted_newest_first(self) -> None:
        a = self.store.record_failure("a", error="x")
        b = self.store.record_failure("b", error="y")
        items = self.store.items()
        ids = [i["arxiv_id"] for i in items]
        self.assertIn(a["arxiv_id"], ids)
        self.assertIn(b["arxiv_id"], ids)


class TestInnerAddStatus(unittest.TestCase):
    def test_extracts_payload_status(self) -> None:
        wrapped = {"status": "ok", "result": {"status": "error", "error": "kaboom"}}
        self.assertEqual(inner_add_status(wrapped), "error")

    def test_defaults_when_missing(self) -> None:
        self.assertEqual(inner_add_status({"status": "ok"}), "")
        self.assertEqual(inner_add_status(None), "")


if __name__ == "__main__":
    unittest.main()
