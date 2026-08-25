"""Plan template library — case-based reasoning for agentic workflows.

Successful plans are saved as named templates; the researcher can re-run them
as-is or use them as planning seeds. This is the classic plan-library pattern:
experience compounds instead of evaporating with each session.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class TemplateStore:
    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "plan_templates.json"
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
        for item in raw.get("templates", []):
            self._items[item["id"]] = item

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"templates": list(self._items.values())}, indent=1))
        os.replace(tmp, self.path)

    def save(self, goal: str, steps: list[dict[str, Any]], planner: str, agent: str = "") -> dict[str, Any]:
        """Upsert by normalized goal so reruns refresh instead of duplicating."""
        key = " ".join(goal.lower().split())
        with self._lock:
            existing = next((t for t in self._items.values() if " ".join(t["goal"].lower().split()) == key), None)
            prev = existing or {}
            tpl = {
                "id": prev.get("id", uuid.uuid4().hex[:12]),
                "goal": goal,
                "steps": steps,
                "planner": planner,
                "agent": agent,
                "uses": int(prev.get("uses", 0)) + 1,
                "created": prev.get("created", utcnow()),
                "updated": utcnow(),
            }
            self._items[tpl["id"]] = tpl
            self._save()
            return dict(tpl)

    def items(self) -> list[dict[str, Any]]:
        with self._lock:
            return sorted(
                (dict(i) for i in self._items.values()),
                key=lambda t: (-t.get("uses", 0), t.get("updated", "")),
            )

    def get(self, template_id: str) -> dict[str, Any] | None:
        with self._lock:
            item = self._items.get(template_id)
            return dict(item) if item else None

    def delete(self, template_id: str) -> bool:
        with self._lock:
            if template_id not in self._items:
                return False
            del self._items[template_id]
            self._save()
            return True
