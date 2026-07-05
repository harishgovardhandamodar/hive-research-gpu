"""Tests for the ingestion queue module."""

from __future__ import annotations

from unittest.mock import MagicMock

from hive_research.ingestion import (
    IngestionQueue,
    STATUS_QUEUED,
    STATUS_DONE,
    STATUS_ERROR,
)


class TestIngestionQueue:
    def setup_method(self) -> None:
        self.queue = IngestionQueue(
            config=MagicMock(),
            llm=MagicMock(),
            kg=MagicMock(),
            pipeline=MagicMock(),
            rag=MagicMock(),
        )

    def test_enqueue(self) -> None:
        r = self.queue.enqueue("1706.03762")
        assert r["status"] == "queued"
        assert r["paper_id"] == "1706.03762"

    def test_enqueue_duplicate(self) -> None:
        self.queue.enqueue("p1")
        r = self.queue.enqueue("p1")
        assert r["status"] == "already_queued"

    def test_get_jobs(self) -> None:
        self.queue.enqueue("p1")
        self.queue.enqueue("p2")
        jobs = self.queue.get_jobs()
        assert len(jobs) == 2

    def test_get_job(self) -> None:
        self.queue.enqueue("p1")
        job = self.queue.get_job("p1")
        assert job is not None
        assert job["paper_id"] == "p1"
        assert job["status"] == STATUS_QUEUED

    def test_get_job_missing(self) -> None:
        assert self.queue.get_job("nonexistent") is None

    def test_set_status(self) -> None:
        self.queue.enqueue("p1")
        self.queue._set_status("p1", STATUS_DONE, "Completed")
        job = self.queue.get_job("p1")
        assert job["status"] == STATUS_DONE

    def test_set_status_no_backwards(self) -> None:
        self.queue.enqueue("p1")
        self.queue._set_status("p1", STATUS_DONE, "Completed")
        self.queue._set_status("p1", STATUS_QUEUED, "Trying to go back")
        job = self.queue.get_job("p1")
        assert job["status"] == STATUS_DONE

    def test_error_status_allowed(self) -> None:
        self.queue.enqueue("p1")
        self.queue._set_status("p1", STATUS_ERROR, "Something broke")
        job = self.queue.get_job("p1")
        assert job["status"] == STATUS_ERROR

    def test_get_events(self) -> None:
        self.queue.enqueue("p1")
        self.queue._set_status("p1", "fetching", "Fetching...")
        events = self.queue.get_events()
        assert len(events) >= 2

    def test_get_stats(self) -> None:
        self.queue.enqueue("p1")
        stats = self.queue.get_stats()
        assert stats["total"] >= 1
        assert "queued" in stats["by_status"]

    def test_clear_done(self) -> None:
        self.queue.enqueue("p1")
        self.queue._set_status("p1", STATUS_DONE, "Done")
        self.queue.enqueue("p2")
        cleared = self.queue.clear_done()
        assert cleared >= 1
