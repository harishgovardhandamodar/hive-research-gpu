"""Feedback capture + reinforcement signals.

The first half of the improvement loop: every Fox answer and paper note can
be rated by the researcher. Ratings are persisted as JSONL and summarized
into actionable hints (weak topics, low-rated modes, papers worth
re-analyzing). The second half — acting on those hints — lives in the
auto-improve pass (see organizer.auto_improve_pass).
"""

from __future__ import annotations

import json
import logging
import threading
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Config

logger = logging.getLogger(__name__)

def utcnow() -> datetime:
    """Naive UTC now (datetime.utcnow() is deprecated in 3.12+)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class FeedbackStore:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.path = Path(config.feedback_dir) / "ratings.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def record(
        self,
        kind: str,
        rating: int,
        comment: str = "",
        **context: Any,
    ) -> dict[str, Any]:
        entry = {
            "ts": utcnow().isoformat(),
            "kind": kind,
            "rating": int(rating),
            "comment": comment[:500],
            **context,
        }
        with self._lock:
            with open(self.path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        logger.info("Feedback recorded: %s rating=%s", kind, rating)
        return entry

    def all_entries(self, limit: int | None = None) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        entries = []
        with open(self.path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return entries[-limit:] if limit else entries

    def low_rated(self, threshold: int | None = None, limit: int = 50) -> list[dict[str, Any]]:
        threshold = threshold if threshold is not None else self.config.feedback_low_rating_threshold
        entries = [e for e in self.all_entries() if e.get("rating", 5) <= threshold]
        return entries[-limit:]

    def summary(self, kind: str | None = None, limit: int = 500) -> dict[str, Any]:
        entries = [e for e in self.all_entries(limit=limit) if kind is None or e["kind"] == kind]
        if not entries:
            return {"count": 0}
        ratings = [e["rating"] for e in entries]
        by_kind = Counter(e["kind"] for e in entries)
        by_mode = Counter(e.get("mode", "") for e in entries if e.get("mode"))
        weak_modes = {m: c for m, c in by_mode.items() if m}
        return {
            "count": len(entries),
            "avg_rating": round(sum(ratings) / len(ratings), 2),
            "low_count": sum(1 for r in ratings if r <= self.config.feedback_low_rating_threshold),
            "by_kind": dict(by_kind),
            "by_mode": dict(weak_modes),
            "recent": entries[-10:],
        }

    def prompt_hints(self, mode: str | None = None) -> list[str]:
        """Distill past criticism into instructions for future answers."""
        hints: list[str] = []
        bad = [
            e for e in self.low_rated(limit=30)
            if (mode is None or e.get("mode") in (None, "", mode)) and e.get("comment")
        ]
        comments = [e["comment"].strip() for e in bad][-8:]
        if comments:
            hints.append("The researcher previously criticized outputs like yours:")
            hints.extend(f"- \"{c}\"" for c in comments)
        return hints


def parse_rating(raw: Any) -> int:
    """Clamp arbitrary client input to a 1..5 int."""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 0
    return max(1, min(5, value))
