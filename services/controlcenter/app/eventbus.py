import asyncio
import json
import logging
import time
import uuid
from collections import deque
from typing import Optional

logger = logging.getLogger("controlcenter.eventbus")


class Event:
    __slots__ = ("id", "ts", "type", "severity", "service", "message", "data")

    def __init__(
        self,
        type: str,
        message: str,
        severity: str = "info",
        service: str = "",
        data: Optional[dict] = None,
    ):
        self.id = uuid.uuid4().hex[:12]
        self.ts = time.time()
        self.type = type
        self.severity = severity
        self.service = service
        self.message = message
        self.data = data or {}

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "ts": self.ts,
            "type": self.type,
            "severity": self.severity,
            "service": self.service,
            "message": self.message,
            "data": self.data,
        }

    def to_sse(self) -> str:
        return f"id: {self.id}\nevent: event\ndata: {json.dumps(self.to_dict())}\n\n"


class EventBus:
    def __init__(self, maxlen: int = 1000):
        self._buffer: deque[Event] = deque(maxlen=maxlen)
        self._subscribers: dict[str, asyncio.Queue] = {}

    def emit(self, event: Event):
        self._buffer.append(event)
        dead = []
        for sub_id, q in self._subscribers.items():
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(sub_id)
        for sub_id in dead:
            self._subscribers.pop(sub_id, None)
            logger.warning("Dropped slow subscriber %s", sub_id)

    def subscribe(self) -> tuple[str, asyncio.Queue]:
        sub_id = uuid.uuid4().hex[:8]
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._subscribers[sub_id] = q
        return sub_id, q

    def unsubscribe(self, sub_id: str):
        self._subscribers.pop(sub_id, None)

    def recent(self, limit: int = 50, service: str = "", severity: str = "", search: str = "") -> list[dict]:
        events = list(self._buffer)
        if service:
            events = [e for e in events if e.service == service]
        if severity:
            events = [e for e in events if e.severity == severity]
        if search:
            search_lower = search.lower()
            events = [e for e in events if search_lower in e.message.lower()]
        return [e.to_dict() for e in events[-limit:]]
