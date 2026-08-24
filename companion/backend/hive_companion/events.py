"""In-process pub/sub fan-out to WebSocket clients."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, asyncio.Queue] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> tuple[str, asyncio.Queue]:
        qid = uuid.uuid4().hex[:8]
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._subscribers[qid] = queue
        return qid, queue

    def unsubscribe(self, qid: str) -> None:
        self._subscribers.pop(qid, None)

    def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        event = {"type": event_type, **payload}
        dead = []
        for qid, queue in self._subscribers.items():
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("subscriber %s full; dropping %s", qid, event_type)
                dead.append(qid)
        for qid in dead:
            self.unsubscribe(qid)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)
