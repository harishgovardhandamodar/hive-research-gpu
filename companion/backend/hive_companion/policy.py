"""Reinforcement policy: learn from accept/reject and outcomes over time.

Every decision the researcher makes (accepting or rejecting a suggestion or
approval) and every tool outcome (ok/error) updates smoothed per-kind and
per-tool weights. Higher-weight suggestion kinds surface first; higher-weight
tools are preferred by the planner. Weights use Laplace smoothing over the
recent event window so a single bad experience never zeroes a behavior but
consistent rejection does demote it.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

WINDOW = 40  # events considered per signal
PRIOR = 2.0  # Laplace prior successes/failures


class ReinforcementPolicy:
    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "policy.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._events: dict[str, deque[bool]] = defaultdict(lambda: deque(maxlen=WINDOW))
        self._load()

    # -- persistence ---------------------------------------------------------

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError):
            return
        for key, values in raw.items():
            self._events[key].extend(bool(v) for v in values[-WINDOW:])

    def _save(self) -> None:
        with self._lock:
            data = {key: list(vals) for key, vals in self._events.items() if vals}
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data))
            os.replace(tmp, self.path)

    # -- learning ------------------------------------------------------------

    def observe(self, signal: str, success: bool) -> None:
        """Record one outcome; signal is like 'suggestion:survey' or 'tool:add_paper'."""
        with self._lock:
            self._events[signal].append(bool(success))
        self._save()
        logger.info("policy %s %s -> %.2f", signal, "ok" if success else "fail", self.weight(signal))

    def weight(self, signal: str) -> float:
        with self._lock:
            events = list(self._events.get(signal, ()))
        if not events:
            return 0.5
        wins = sum(events)
        return round((wins + PRIOR) / (len(events) + PRIOR * 2), 3)

    def weights(self, prefix: str = "") -> dict[str, float]:
        keys = [k for k in self._events if k.startswith(prefix)]
        return {k: self.weight(k) for k in sorted(keys)}

    def ranked(self, signals: list[str]) -> list[str]:
        """Order signals by learned weight, strongest first."""
        return sorted(signals, key=self.weight, reverse=True)

    def planner_hints(self) -> str:
        """Distill preferences into planner instructions."""
        hints = []
        tool_weights = self.weights("tool:")
        failing = [k.split(":", 1)[1] for k, w in tool_weights.items() if w < 0.35]
        if failing:
            hints.append(f"Tools recently unreliable here, prefer alternatives: {', '.join(failing)}")
        preferred = [k.split(":", 1)[1] for k, w in tool_weights.items() if w >= 0.85][:5]
        if preferred:
            hints.append(f"Tools the researcher's workflow favors: {', '.join(preferred)}")
        rejected = [k.split(":", 1)[1] for k, w in self.weights("suggestion:").items() if w < 0.35]
        if rejected:
            hints.append(f"Suggestion types often rejected, propose sparingly: {', '.join(rejected)}")
        return "\n".join(hints)

    def snapshot(self) -> dict[str, Any]:
        return {"weights": self.weights(), "window": WINDOW}
