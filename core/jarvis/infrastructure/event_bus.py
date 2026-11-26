"""Monotonic sequenced domain event bus for SSE / IPC stream with cursor resumption."""

from __future__ import annotations

import asyncio
import contextlib
import threading
import uuid
from collections import deque
from datetime import UTC, datetime
from typing import Any

from jarvis.domain.models import SequencedEvent


class SequencedEventBus:
    """Thread-safe monotonic event publisher supporting sequence cursor replay."""

    def __init__(self, max_history: int = 2000) -> None:
        self._lock = threading.Lock()
        self._seq = 0
        self._history: deque[SequencedEvent] = deque(maxlen=max_history)
        self._subscribers: set[asyncio.Queue[SequencedEvent]] = set()

    @property
    def current_seq(self) -> int:
        with self._lock:
            return self._seq

    def publish(
        self,
        *,
        event_type: str,
        correlation_id: str,
        payload: dict[str, Any],
        request_id: str | None = None,
    ) -> SequencedEvent:
        with self._lock:
            self._seq += 1
            event = SequencedEvent(
                event_id=str(uuid.uuid4()),
                seq=self._seq,
                request_id=request_id,
                correlation_id=correlation_id,
                type=event_type,
                occurred_at=datetime.now(tz=UTC),
                payload=payload,
            )
            self._history.append(event)
            queues = list(self._subscribers)

        for queue in queues:
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(event)
        return event

    def replay_after(self, after_seq: int) -> tuple[list[SequencedEvent], bool]:
        """Return events strictly newer than after_seq and a flag indicating whether cursor expired."""
        with self._lock:
            if not self._history:
                return ([], False)
            oldest_seq = self._history[0].seq
            resync_required = after_seq > 0 and after_seq < oldest_seq - 1
            events = [e for e in self._history if e.seq > after_seq]
            return (events, resync_required)

    def subscribe(self, maxsize: int = 256) -> asyncio.Queue[SequencedEvent]:
        queue: asyncio.Queue[SequencedEvent] = asyncio.Queue(maxsize=maxsize)
        with self._lock:
            self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[SequencedEvent]) -> None:
        with self._lock:
            self._subscribers.discard(queue)
