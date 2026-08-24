"""Proactive engine: watch live app state and surface ranked suggestions.

Each cycle gathers cheap signals through the main API (un-analyzed papers,
poor feedback trends, watch-pool backlog, idle vault). Every signal becomes a
suggestion scored by signal strength x the learned acceptance weight for its
kind — so the companion proposes more of what the researcher historically
accepts and goes quiet about what they reject.
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
from typing import Any, Callable, Coroutine

from .events import EventBus
from .hive_client import HiveApiError, HiveClient
from .policy import ReinforcementPolicy

logger = logging.getLogger(__name__)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class SuggestionStore:
    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "suggestions.json"
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
            self._items[item["id"]] = item

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"items": list(self._items.values())[-200:]}, indent=1))
        os.replace(tmp, self.path)

    def upsert(self, key: str, suggestion: dict[str, Any]) -> dict[str, Any] | None:
        """Insert unless an open suggestion with the same dedupe key exists."""
        with self._lock:
            for item in self._items.values():
                if item.get("status") == "open" and item.get("dedupe_key") == key:
                    return None
            suggestion["id"] = uuid.uuid4().hex[:12]
            suggestion["created"] = utcnow()
            suggestion["status"] = "open"
            suggestion["dedupe_key"] = key
            self._items[suggestion["id"]] = suggestion
            self._save()
            return suggestion

    def decide(self, suggestion_id: str, accepted: bool) -> dict[str, Any] | None:
        with self._lock:
            item = self._items.get(suggestion_id)
            if not item or item.get("status") != "open":
                return None
            item["status"] = "accepted" if accepted else "rejected"
            item["decided"] = utcnow()
            self._save()
            return item

    def open(self) -> list[dict[str, Any]]:
        with self._lock:
            items = [dict(i) for i in self._items.values() if i.get("status") == "open"]
        return sorted(items, key=lambda s: s.get("score", 0), reverse=True)

    def recent(self, limit: int = 30) -> list[dict[str, Any]]:
        with self._lock:
            items = sorted(self._items.values(), key=lambda s: s.get("created", ""))
        return [dict(i) for i in items[-limit:]]

    def open_keys(self) -> set[str]:
        with self._lock:
            return {i["dedupe_key"] for i in self._items.values() if i.get("status") == "open"}


class ProactiveEngine:
    def __init__(
        self,
        client: HiveClient,
        store: SuggestionStore,
        policy: ReinforcementPolicy,
        bus: EventBus,
        interval_s: float = 300.0,
    ) -> None:
        self.client = client
        self.store = store
        self.policy = policy
        self.bus = bus
        self.interval_s = interval_s
        self._task: asyncio.Task | None = None
        self.last_cycle: dict[str, Any] = {"at": None, "signals": {}, "new": 0}

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
                await self.run_cycle()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("proactive cycle failed")
            await asyncio.sleep(self.interval_s)

    async def run_cycle(self) -> list[dict[str, Any]]:
        checks: list[tuple[str, Callable[..., Coroutine[Any, Any, dict[str, Any] | None]]]] = [
            ("unanalyzed_notes", self._signal_unanalyzed),
            ("feedback_trend", self._signal_feedback),
            ("pool_backlog", self._signal_pool),
            ("vault_idle", self._signal_idle),
        ]
        strengths: dict[str, float] = {}
        created: list[dict[str, Any]] = []
        for name, check in checks:
            try:
                result = await check()
            except HiveApiError as exc:
                logger.debug("signal %s unavailable: %s", name, exc)
                continue
            if result is None:
                continue
            strength = float(result.pop("strength"))
            strengths[name] = strength
            if strength <= 0:
                continue
            weight = self.policy.weight(f"suggestion:{result['kind']}")
            result["score"] = round(strength * weight * 2, 3)
            result["signal"] = name
            key = f"{name}:{result.pop('dedupe_key', '')}"
            new = self.store.upsert(key, result)
            if new:
                created.append(new)
                self.bus.publish("suggestion", {k: v for k, v in new.items()})
        self.last_cycle = {"at": utcnow(), "signals": strengths, "new": len(created)}
        logger.info("proactive cycle: %s, %d new suggestions", strengths, len(created))
        return created

    # -- signals ---------------------------------------------------------

    async def _signal_unanalyzed(self) -> dict[str, Any] | None:
        stats = await self.client.stats()
        total = int(stats.get("papers", 0) or 0)
        notes = int(stats.get("notes", stats.get("analysed", 0)) or 0)
        pending = max(total - notes, 0)
        if pending < 2:
            return None
        strength = min(pending / 10.0, 1.0)
        return {
            "kind": "notes_refresh",
            "title": f"{pending} papers lack analysis",
            "rationale": f"Library has {total} papers but only {notes} analyzed notes. Refresh brings them into RAG/KG.",
            "tool": "notes.refresh_all",
            "args": {},
            "dedupe_key": "global",
            "strength": strength,
        }

    async def _signal_feedback(self) -> dict[str, Any] | None:
        summary = await self.client.feedback_summary()
        count = int(summary.get("count", 0) or 0)
        if count == 0:
            return None
        low = int(summary.get("low_count", 0) or 0)
        if low < 2:
            return None
        strength = min(low / max(count, 1), 1.0)
        return {
            "kind": "improve",
            "title": f"{low} outputs rated poorly",
            "rationale": "Reinforcement pass re-analyzes low-rated notes with your criticism injected as hints.",
            "tool": "improve.run",
            "args": {},
            "dedupe_key": "global",
            "strength": strength,
        }

    async def _signal_pool(self) -> dict[str, Any] | None:
        topics_data = await self.client.pool_topics()
        topics = topics_data.get("topics", []) if isinstance(topics_data, dict) else []
        if not topics:
            return None
        top = topics[0] if isinstance(topics[0], str) else topics[0].get("topic", "")
        if not top:
            return None
        return {
            "kind": "pool_import",
            "title": f"Watch topic '{top}' may have fresh matches",
            "rationale": "The arxiv watch pool is observing new preprints for this topic; importing keeps the library current.",
            "tool": "pool.import_topic",
            "args": {"topic": top},
            "dedupe_key": top,
            "strength": 0.5,
        }

    async def _signal_idle(self) -> dict[str, Any] | None:
        digest = await self.client.digest()
        total_new = int(digest.get("total_new", 0) or 0)
        if total_new > 0:
            return None
        return {
            "kind": "digest",
            "title": "Vault looks quiet — want a catch-up digest?",
            "rationale": "No new pool papers in the current window; a digest summarizes where the research stands.",
            "tool": "digest.daily",
            "args": {},
            "dedupe_key": "global",
            "strength": 0.3,
        }
