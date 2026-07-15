"""Ingestion queue with per-paper status tracking and real-time logging."""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from datetime import datetime
from typing import Any

from .arxiv_fetcher import fetch_by_id_with_meta
from .config import Config
from .gpu import GPUManager
from .graph import KnowledgeGraph
from .llm import LLMInterface
from .pipeline import PaperPipeline
from .rag import RAGEngine

logger = logging.getLogger(__name__)


STATUS_QUEUED = "queued"
STATUS_FETCHING = "fetching"
STATUS_DOWNLOADING = "downloading"
STATUS_EXTRACTING = "extracting"
STATUS_PARSING = "parsing"
STATUS_ANALYZING = "analyzing"
STATUS_GRAPHING = "graphing"
STATUS_INDEXING = "indexing"
STATUS_DONE = "done"
STATUS_ERROR = "error"

STATUS_ORDER = {
    STATUS_QUEUED: 0,
    STATUS_FETCHING: 1,
    STATUS_DOWNLOADING: 2,
    STATUS_EXTRACTING: 3,
    STATUS_PARSING: 4,
    STATUS_ANALYZING: 5,
    STATUS_GRAPHING: 6,
    STATUS_INDEXING: 7,
    STATUS_DONE: 8,
    STATUS_ERROR: -1,
}


class IngestionQueue:
    """Async paper ingestion queue with per-paper job tracking.

    Each job goes through status stages::
        queued → fetching → downloading → extracting → parsing →
        analyzing → graphing → indexing → done

    Status updates are broadcast via an in-memory buffer that the
    dashboard polls via ``/api/ingestion/status``.
    """

    def __init__(
        self,
        config: Config,
        llm: LLMInterface,
        kg: KnowledgeGraph,
        pipeline: PaperPipeline,
        rag: RAGEngine,
        gpu_mgr: GPUManager | None = None,
    ) -> None:
        self.config = config
        self.llm = llm
        self.kg = kg
        self.pipeline = pipeline
        self.rag = rag
        self.gpu_mgr = gpu_mgr
        self._lock = threading.Lock()
        self._jobs: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._events: list[dict[str, Any]] = []
        self._events_max = 200
        self._thread: threading.Thread | None = None

    # ── Job Management ──

    def enqueue(self, paper_id: str, model: str | None = None) -> dict[str, Any]:
        """Add a paper to the ingestion queue. Returns immediately."""
        with self._lock:
            if paper_id in self._jobs:
                existing = self._jobs[paper_id]
                if existing["status"] not in (STATUS_DONE, STATUS_ERROR):
                    return {"status": "already_queued", "paper_id": paper_id}
            self._jobs[paper_id] = {
                "paper_id": paper_id,
                "model": model,
                "status": STATUS_QUEUED,
                "progress": 0,
                "message": "Waiting in queue",
                "started": None,
                "finished": None,
                "error": None,
            }
            self._emit(paper_id, STATUS_QUEUED, "Queued")
        # Start worker thread if not running
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._worker, daemon=True)
            self._thread.start()
        return {"status": "queued", "paper_id": paper_id}

    def _set_status(self, paper_id: str, status: str, message: str, progress: int | None = None) -> None:
        with self._lock:
            job = self._jobs.get(paper_id)
            if not job:
                return
            old_status = job["status"]
            # Only allow forward progress
            if STATUS_ORDER.get(status, -1) < STATUS_ORDER.get(old_status, -1) and status != STATUS_ERROR:
                return
            job["status"] = status
            job["message"] = message
            if progress is not None:
                job["progress"] = progress
            if status == STATUS_QUEUED and job["started"] is None:
                job["started"] = datetime.now().isoformat(timespec="seconds")
            elif status == STATUS_DONE or status == STATUS_ERROR:
                job["finished"] = datetime.now().isoformat(timespec="seconds")
            self._emit(paper_id, status, message)
            # Also log via standard logging (appears in activity log)
            log_msg = f"{paper_id}:{status} — {message}"
            if status == STATUS_ERROR:
                logger.error(log_msg)
            elif status == STATUS_DONE:
                logger.info(log_msg)
            else:
                logger.debug(log_msg)

    def _emit(self, paper_id: str, status: str, message: str) -> None:
        entry = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "paper_id": paper_id,
            "status": status,
            "message": message,
        }
        self._events.append(entry)
        if len(self._events) > self._events_max:
            self._events = self._events[-self._events_max:]

    # ── Worker ──

    def _worker(self) -> None:
        """Background loop that processes jobs from the queue."""
        while True:
            job = self._dequeue_next()
            if job is None:
                time.sleep(0.5)
                continue
            self._process_job(job)

    def _dequeue_next(self) -> dict[str, Any] | None:
        with self._lock:
            for pid, job in self._jobs.items():
                if job["status"] == STATUS_QUEUED:
                    return job
            return None

    def _process_job(self, job: dict[str, Any]) -> None:
        pid = job["paper_id"]
        model = job.get("model")
        try:
            # 1. Fetch metadata
            self._set_status(pid, STATUS_FETCHING, "Fetching metadata from arXiv", 10)
            result = fetch_by_id_with_meta(pid)
            if result["status"] == "error":
                raise RuntimeError(result.get("message", "arXiv fetch failed"))
            paper = result["paper"]

            # 2. Check existing
            existing = self.kg.get_paper(pid)
            if existing:
                self._set_status(pid, STATUS_DONE, "Already exists in knowledge base", 100)
                return

            # 3. Download PDF
            self._set_status(pid, STATUS_DOWNLOADING, "Downloading PDF", 20)
            # 4. Process through pipeline
            self._set_status(pid, STATUS_EXTRACTING, "Extracting text from PDF", 35)
            pipeline_result = self.pipeline.process_paper(paper, model=model)

            if pipeline_result.get("status") == "added":
                # 5. RAG indexing
                self._set_status(pid, STATUS_INDEXING, "Indexing for RAG search", 75)
                pdf_path = self.config.papers_dir / f"{pid}.pdf"
                if pdf_path.exists():
                    from .parser import cached_extract_text as _ce
                    pdf_text = _ce(pdf_path)
                    if pdf_text:
                        n = self.rag.index_paper(pid, pdf_text)
                        pipeline_result["rag_chunks"] = n

                self._set_status(pid, STATUS_DONE, f"Added: {pipeline_result.get('concepts', 0)} concepts, {pipeline_result.get('tags', 0)} tags", 100)
            else:
                self._set_status(pid, STATUS_DONE, pipeline_result.get("status", "done"), 100)

        except Exception as e:
            logger.error("Ingestion failed for %s: %s", pid, e, exc_info=True)
            self._set_status(pid, STATUS_ERROR, f"Failed: {e}", 0)

    # ── Query ──

    def get_jobs(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(j) for j in self._jobs.values()]

    def get_job(self, paper_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(paper_id)
            return dict(job) if job else None

    def get_events(self, since: str | None = None, n: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            events = self._events
            if since:
                events = [e for e in events if e["time"] >= since]
            return events[-n:]

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            total = len(self._jobs)
            by_status: dict[str, int] = {}
            for j in self._jobs.values():
                s = j["status"]
                by_status[s] = by_status.get(s, 0) + 1
            return {"total": total, "by_status": by_status}

    def clear_done(self) -> int:
        with self._lock:
            before = len(self._jobs)
            self._jobs = OrderedDict(
                (k, v) for k, v in self._jobs.items()
                if v["status"] not in (STATUS_DONE, STATUS_ERROR)
            )
            return before - len(self._jobs)
