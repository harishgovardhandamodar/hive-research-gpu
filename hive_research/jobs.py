"""Thread-safe job/stage registry for long-running processes.

Every ingestion (and other slow operation) registers itself here so the UI
and Fox can report live per-stage progress:

  fetch → pdf → parse → analyze → graph → notes → rag → lineage

Stages are coarse on purpose: they map 1:1 to what a researcher wants to
know ("is my paper analyzed yet?").
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

STAGE_ORDER = [
    "fetch",     # arXiv metadata fetch
    "pdf",       # PDF download
    "parse",     # text + figure extraction
    "analyze",   # LLM analysis (tags, summary, concepts)
    "graph",     # knowledge graph population
    "notes",     # vault note writing
    "rag",       # RAG chunk embedding
    "lineage",   # citation lineage fetch
]

TERMINAL_STATUSES = {"done", "error", "cancelled"}


@dataclass
class Stage:
    name: str
    status: str = "pending"  # pending | running | done | error | skipped
    detail: str = ""
    t_start: float = 0.0
    t_end: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "detail": self.detail[:200],
            "elapsed_s": round(self.t_end - self.t_start, 2) if self.t_end else None,
        }


@dataclass
class Job:
    id: str
    kind: str                  # ingest | import_search | survey | reanalyze | web_ingest
    label: str
    meta: dict[str, Any] = field(default_factory=dict)
    status: str = "running"    # running | done | error | cancelled
    created: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    stages: dict[str, Stage] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.stages:
            self.stages = {name: Stage(name=name) for name in STAGE_ORDER}

    def to_dict(self) -> dict[str, Any]:
        ordered = [self.stages[s].to_dict() for s in STAGE_ORDER if s in self.stages]
        ordered += [s.to_dict() for k, s in self.stages.items() if k not in STAGE_ORDER]
        return {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "status": self.status,
            "created": self.created,
            "meta": self.meta,
            "stages": ordered,
            "active": self.status == "running",
        }


class JobRegistry:
    def __init__(self, history_max: int = 200) -> None:
        self._jobs: dict[str, Job] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()
        self._history_max = history_max

    # -- lifecycle ----------------------------------------------------------

    def start(self, kind: str, label: str, stages: list[str] | None = None, **meta: Any) -> Job:
        job_id = uuid.uuid4().hex[:12]
        job = Job(id=job_id, kind=kind, label=label, meta=meta)
        if stages:
            job.stages = {name: Stage(name=name) for name in stages}
        with self._lock:
            self._jobs[job_id] = job
            self._order.append(job_id)
            while len(self._order) > self._history_max:
                old = self._order.pop(0)
                self._jobs.pop(old, None)
        return job

    # -- stage updates -------------------------------------------------------

    def stage(
        self,
        job: Job,
        name: str,
        status: str,
        detail: str = "",
    ) -> None:
        with self._lock:
            st = job.stages.get(name)
            if st is None:
                st = job.stages[name] = Stage(name=name)
            st.status = status
            st.detail = detail
            if status == "running":
                st.t_start = time.time()
            elif status in ("done", "error", "skipped"):
                st.t_end = time.time()
                if not st.t_start:
                    st.t_start = st.t_end - 0.001
            if status == "error":
                job.status = "error"
            elif status == "cancelled":
                job.status = "cancelled"

    class _StageCtx:
        """Context manager: mark stage running → done/error automatically."""

        def __init__(self, registry: "JobRegistry", job: "Job", name: str) -> None:
            self._reg, self._job, self._name = registry, job, name

        def __enter__(self) -> None:
            self._reg.stage(self._job, self._name, "running")
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            if exc_type is None:
                self._reg.stage(self._job, self._name, "done")
            else:
                self._reg.stage(self._job, self._name, "error", str(exc))
            return False  # never swallow exceptions

    def ctx(self, job: Job, name: str) -> "JobRegistry._StageCtx":
        return JobRegistry._StageCtx(self, job, name)

    def finish(self, job: Job, error: str | None = None) -> None:
        with self._lock:
            if job.status == "running":
                job.status = "error" if error else "done"

    # -- queries -------------------------------------------------------------

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(
        self,
        active_only: bool = False,
        kind: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        with self._lock:
            ids = list(reversed(self._order))
        out = []
        for jid in ids:
            job = self._jobs.get(jid)
            if job is None:
                continue
            if active_only and job.status != "running":
                continue
            if kind and job.kind != kind:
                continue
            out.append(job.to_dict())
            if len(out) >= limit:
                break
        return out

    def summary(self) -> dict[str, Any]:
        with self._lock:
            jobs = list(self._jobs.values())
        running = sum(1 for j in jobs if j.status == "running")
        failed = sum(1 for j in jobs if j.status == "error")
        done = sum(1 for j in jobs if j.status == "done")
        recent = list(reversed(jobs))[:10]
        return {
            "running": running,
            "failed": failed,
            "done": done,
            "total": len(jobs),
            "papers_in_flight": [j.label for j in recent if j.status == "running"],
        }

    def human_summary(self) -> str:
        """Compact text for Fox status answers."""
        s = self.summary()
        lines = [f"{s['running']} running, {s['done']} done, {s['failed']} failed (of {s['total']} tracked)"]
        with self._lock:
            recent = [self._jobs[jid] for jid in reversed(self._order[-8:]) if jid in self._jobs]
        for j in recent:
            cur = next((st.name for st in j.stages.values() if st.status == "running"), j.status)
            icon = {"done": "[ok]", "error": "[ERR]", "running": "[..]"}.get(j.status, "[..]")
            lines.append(f"{icon} {j.label} — {cur}")
        return "\n".join(lines)


_registry: JobRegistry | None = None
_registry_lock = threading.Lock()


def get_registry() -> JobRegistry:
    global _registry
    with _registry_lock:
        if _registry is None:
            _registry = JobRegistry()
        return _registry
