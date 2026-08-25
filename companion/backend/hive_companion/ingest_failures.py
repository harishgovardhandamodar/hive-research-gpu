"""Ledger of failed paper ingestions, so failures are visible and retryable.

The companion records one entry per arxiv id whose library.add_paper step
failed (from plan events), and clears it when a later attempt succeeds. The
proactive engine turns open entries into a rerun suggestion; the retry tool
and /api/ingest endpoints read and mutate the same store.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class IngestFailureStore:
    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "ingest_failures.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._items: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError):
            return
        for item in raw.get("items", []):
            self._items[item["arxiv_id"]] = item

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"items": list(self._items.values())}, indent=1))
        os.replace(tmp, self.path)

    def record_failure(self, arxiv_id: str, title: str = "", error: str = "") -> dict[str, Any]:
        with self._lock:
            item = self._items.get(arxiv_id, {"arxiv_id": arxiv_id, "attempts": 0})
            item["title"] = title or item.get("title", "")
            if error:
                item["error"] = error[:300]
            item["attempts"] = int(item.get("attempts", 0)) + 1
            item["failed_at"] = utcnow()
            self._items[arxiv_id] = item
            self._save()
            return dict(item)

    def record_success(self, arxiv_id: str) -> None:
        with self._lock:
            if arxiv_id in self._items:
                del self._items[arxiv_id]
                self._save()

    def dismiss(self, arxiv_id: str) -> bool:
        """Drop an entry without a successful ingestion (e.g. withdrawn paper)."""
        with self._lock:
            if arxiv_id not in self._items:
                return False
            del self._items[arxiv_id]
            self._save()
            return True

    def items(self) -> list[dict[str, Any]]:
        with self._lock:
            return sorted(
                (dict(i) for i in self._items.values()),
                key=lambda i: i.get("failed_at", ""),
                reverse=True,
            )

    def count(self) -> int:
        with self._lock:
            return len(self._items)


def inner_add_status(event_result: Any) -> str:
    """Status reported by hive inside an executor step result.

    registry.execute wraps handler output as {status: "ok", result: <payload>},
    so a pipeline that failed server-side but returned HTTP 200 still lands
    here with payload status "error".
    """
    payload = (event_result or {}).get("result") if isinstance(event_result, dict) else None
    if isinstance(payload, dict):
        status = payload.get("status")
        if isinstance(status, str):
            return status
    return ""
