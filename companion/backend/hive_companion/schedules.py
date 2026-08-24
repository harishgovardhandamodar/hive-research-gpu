"""Scheduled auto-goals: recurring research tasks on a cadence.

A schedule stores a goal, an autonomy mode and a cadence (daily or weekly
with a weekday). A background loop checks every minute; when a schedule is
due it launches the goal through the normal governed plan pipeline.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def is_due(sch: dict[str, Any], now: datetime) -> bool:
    if not sch.get("enabled", True):
        return False
    cadence = sch.get("cadence", "daily")
    if cadence == "weekly" and now.weekday() != int(sch.get("weekday", 0)):
        return False
    last = sch.get("last_run")
    if not last:
        return True
    try:
        elapsed = now.timestamp() - datetime.fromisoformat(last).timestamp()
    except (TypeError, ValueError):
        return True
    interval_h = 168 if cadence == "weekly" else 24
    return elapsed >= interval_h * 3600


class ScheduleStore:
    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "schedules.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()  # reentrant: mutators hold it across _save()
        self._items: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError):
            return
        for item in raw.get("items", []):
            self._items[item["id"]] = item

    def _save(self) -> None:
        with self._lock:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"items": list(self._items.values())}, indent=1))
            os.replace(tmp, self.path)

    def add(self, goal: str, mode: str, cadence: str, weekday: int = 0) -> dict[str, Any]:
        sch = {
            "id": uuid.uuid4().hex[:10],
            "goal": goal[:500],
            "mode": mode,
            "cadence": cadence,
            "weekday": int(weekday),
            "enabled": True,
            "last_run": None,
            "created": utcnow().isoformat(),
        }
        with self._lock:
            self._items[sch["id"]] = sch
            self._save()
        return sch

    def remove(self, sid: str) -> bool:
        with self._lock:
            if sid in self._items:
                del self._items[sid]
                self._save()
                return True
        return False

    def toggle(self, sid: str) -> dict[str, Any] | None:
        with self._lock:
            item = self._items.get(sid)
            if item:
                item["enabled"] = not item.get("enabled", True)
                self._save()
            return item

    def due(self, now: datetime | None = None) -> list[dict[str, Any]]:
        now = now or utcnow()
        return [s for s in self._items.values() if is_due(s, now)]

    def mark_ran(self, sid: str) -> None:
        with self._lock:
            item = self._items.get(sid)
            if item:
                item["last_run"] = utcnow().isoformat()
                self._save()

    def all(self) -> list[dict[str, Any]]:
        with self._lock:
            return sorted(self._items.values(), key=lambda s: s["created"])


class GoalScheduler:
    def __init__(
        self,
        store: ScheduleStore,
        launcher: Callable[[str, str], Awaitable[Any]],
    ) -> None:
        self.store = store
        self.launcher = launcher
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                for sch in self.store.due():
                    logger.info("schedule %s firing: %s", sch["id"], sch["goal"][:60])
                    try:
                        await self.launcher(sch["goal"], sch["mode"])
                        self.store.mark_ran(sch["id"])
                    except Exception:
                        logger.exception("scheduled goal failed")
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("scheduler tick failed")
            await asyncio.sleep(60)

    async def run_pending_now(self) -> int:
        """Manual trigger (API button): fire every due schedule immediately."""
        fired = 0
        for sch in self.store.due():
            await self.launcher(sch["goal"], sch["mode"])
            self.store.mark_ran(sch["id"])
            fired += 1
        return fired
