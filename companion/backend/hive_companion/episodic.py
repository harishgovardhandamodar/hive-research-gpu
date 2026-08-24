"""Episodic memory: durable, searchable records of everything that happens.

An episode is one discrete experience — a goal set, a plan made, a step run,
an observation gathered, a suggestion accepted or rejected, a conversation
turn. Episodes are append-only JSONL with keyword retrieval and session
summaries; they are what the agent consults before acting ("what happened
last time I did this?") and what the GUI timeline renders.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _tokenize(text: str) -> set[str]:
    return {t for t in "".join(c if c.isalnum() else " " for c in text.lower()).split() if len(t) > 1}


class EpisodeStore:
    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "episodes.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        episodes = []
        with open(self.path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    episodes.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return episodes

    def append(self, kind: str, summary: str, session_id: str = "", goal_id: str = "", **context: Any) -> dict[str, Any]:
        episode = {
            "id": uuid.uuid4().hex[:12],
            "ts": utcnow().isoformat(),
            "kind": kind,
            "summary": summary[:500],
            "session_id": session_id,
            "goal_id": goal_id,
            "context": context,
        }
        with self._lock:
            with open(self.path, "a") as f:
                f.write(json.dumps(episode) + "\n")
        logger.info("episode %s: %s", kind, episode["summary"][:80])
        return episode

    def recent(self, limit: int = 50, kind: str | None = None, goal_id: str | None = None) -> list[dict[str, Any]]:
        episodes = self._load()
        if kind:
            episodes = [e for e in episodes if e["kind"] == kind]
        if goal_id:
            episodes = [e for e in episodes if e.get("goal_id") == goal_id]
        return episodes[-limit:]

    def retrieve(self, query: str, limit: int = 8, kinds: list[str] | None = None) -> list[dict[str, Any]]:
        """Keyword-overlap retrieval over summary + context, newest first."""
        q_tokens = _tokenize(query)
        if not q_tokens:
            return []
        scored: list[tuple[float, dict[str, Any]]] = []
        for ep in self._load():
            if kinds and ep["kind"] not in kinds:
                continue
            haystack = ep["summary"] + " " + ep["kind"] + " " + json.dumps(ep.get("context", {}), default=str)
            tokens = _tokenize(haystack)
            if not tokens:
                continue
            overlap = len(q_tokens & tokens)
            if overlap == 0:
                continue
            score = overlap / (len(q_tokens) ** 0.5)
            scored.append((score, ep))
        scored.sort(key=lambda pair: (pair[0], pair[1]["ts"]))
        return [ep for _, ep in reversed(scored[-limit:])]

    def summarize_session(self, session_id: str) -> dict[str, Any]:
        episodes = [e for e in self._load() if e.get("session_id") == session_id]
        if not episodes:
            return {"session_id": session_id, "count": 0}
        kinds = Counter(e["kind"] for e in episodes)
        goals = [e["summary"] for e in episodes if e["kind"] == "goal"]
        failures = [e for e in episodes if e.get("context", {}).get("status") == "failed"]
        return {
            "session_id": session_id,
            "count": len(episodes),
            "started": episodes[0]["ts"],
            "last": episodes[-1]["ts"],
            "by_kind": dict(kinds),
            "goals": goals,
            "failures": [e["summary"] for e in failures][-5:],
            "narrative": (
                f"Session touched {len(episodes)} events across {len(kinds)} kinds "
                f"(goals: {len(goals)}, failures: {len(failures)})."
            ),
        }

    def context_for_prompt(self, query: str, limit: int = 6) -> str:
        relevant = self.retrieve(query, limit=limit)
        if not relevant:
            return ""
        lines = []
        for ep in relevant:
            ctx = {k: v for k, v in ep.get("context", {}).items() if k != "result"}
            lines.append(f"- [{ep['kind']}] {ep['ts'][:16]} {ep['summary']} {_compact(ctx)}")
        return "\n".join(lines)

    def stats(self) -> dict[str, Any]:
        episodes = self._load()
        return {
            "count": len(episodes),
            "by_kind": dict(Counter(e["kind"] for e in episodes)),
        }


def _compact(d: dict[str, Any], max_len: int = 120) -> str:
    if not d:
        return ""
    text = json.dumps(d, default=str)[:max_len]
    return f" ({text})"
