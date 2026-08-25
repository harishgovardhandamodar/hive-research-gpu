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
from typing import TYPE_CHECKING, Any, Callable, Coroutine

from .cite import topic_drift
from .events import EventBus
from .hive_client import HiveApiError, HiveClient
from .policy import ReinforcementPolicy

if TYPE_CHECKING:
    from .episodic import EpisodeStore
    from .ingest_failures import IngestFailureStore

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
        data_dir: Path | None = None,
        failures: IngestFailureStore | None = None,
        episodes: EpisodeStore | None = None,
    ) -> None:
        self.client = client
        self.store = store
        self.policy = policy
        self.bus = bus
        self.interval_s = interval_s
        self.failures = failures
        self.episodes = episodes
        self.baseline_path = (data_dir / "topic_baseline.json") if data_dir else None
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
            ("topic_drift", self._signal_topic_drift),
            ("ingest_failures", self._signal_ingest_failures),
            ("memory_consolidation", self._signal_memory),
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
            new_shares = result.pop("_new_shares", None)
            new = self.store.upsert(key, result)
            if new:
                # adopt the new distribution so one drift event fires once
                self._save_baseline(new_shares or {})
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

    async def _signal_memory(self) -> dict[str, Any] | None:
        """Generative-Agents style nudge: lots of raw episodes and no recent
        consolidation means experience is accumulating without being distilled."""
        if self.episodes is None:
            return None
        stats = self.episodes.stats()
        total = int(stats.get("count", 0) or 0)
        if total < 150:
            return None
        insights = self.episodes.recent(kind="insight", limit=1)
        by_kind = stats.get("by_kind", {})
        if total - int(by_kind.get("insight", 0) or 0) < 150:
            return None
        return {
            "kind": "memory_consolidation",
            "title": f"{total} episodes of experience not yet distilled",
            "rationale": (
                "Reflection turns the activity log into durable research insights "
                "(what you work on, what works). Run memory consolidation?"
            ),
            "tool": "memory.reflect",
            "args": {},
            "dedupe_key": f"e{total // 150}",
            "strength": 0.45,
        }

    async def _signal_ingest_failures(self) -> dict[str, Any] | None:
        if self.failures is None:
            return None
        items = self.failures.items()
        if not items:
            return None
        count = len(items)
        label = ", ".join(str(i["arxiv_id"]) for i in items[:3]) + ("…" if count > 3 else "")
        return {
            "kind": "ingest_retry",
            "title": f"{count} paper ingestion{'s' if count > 1 else ''} failed — rerun?",
            "rationale": (
                f"Failed: {label}. Re-running re-downloads and re-analyzes them into the knowledge graph."
            ),
            "tool": "library.retry_failed",
            "args": {},
            # attempts in the key so a still-failing rerun raises a fresh suggestion
            "dedupe_key": ":".join(sorted(str(i["arxiv_id"]) for i in items))
            + f":a{max(int(i.get('attempts', 1)) for i in items)}",
            "strength": min(0.4 + 0.15 * count, 1.0),
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


    # -- drift ------------------------------------------------------------

    def _load_baseline(self) -> dict[str, float] | None:
        if not self.baseline_path or not self.baseline_path.exists():
            return None
        try:
            return json.loads(self.baseline_path.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    def _save_baseline(self, shares: dict[str, float]) -> None:
        if not self.baseline_path:
            return
        tmp = self.baseline_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(shares))
        os.replace(tmp, self.baseline_path)

    async def _signal_topic_drift(self) -> dict[str, Any] | None:
        """Compare cluster size shares against the stored baseline."""
        clusters = await self.client.get("/api/graph/clusters")
        cl = clusters.get("clusters", clusters if isinstance(clusters, list) else [])
        total = sum(int(c.get("size", 0)) for c in cl) or 1
        shares = {str(c.get("label", c.get("id", i))): int(c.get("size", 0)) / total for i, c in enumerate(cl)}
        baseline = self._load_baseline()
        if baseline is None:
            self._save_baseline(shares)
            return None
        drifted = topic_drift(shares, baseline, threshold=0.08)
        rising = [d for d in drifted if d["direction"] == "rising"]
        if not rising:
            return None
        top = rising[0]
        return {
            "kind": "topic_drift",
            "title": f"Library mix shifting toward “{top['topic']}”",
            "rationale": (
                f"Cluster share changed by {top['delta']:+.0%} since the last baseline. "
                "Watching this topic keeps new preprints flowing into the pool."
            ),
            "tool": "pool.watch_topic",
            "args": {"topic": top["topic"]},
            "dedupe_key": top["topic"],
            "strength": min(abs(top["delta"]) * 4, 1.0),
            "_new_shares": shares,
        }
