from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol

# Events that are persisted for replay. Token deltas are deliberately excluded: at one row
# per token they would dominate write volume on a free-tier database and nobody replays
# them anyway.
PERSISTED_EVENT_TYPES = {
    "run_started",
    "step",
    "tool_call",
    "tool_result",
    "citations",
    "usage",
    "error",
    "run_finished",
}


@dataclass
class RunEvent:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    seq: int = 0

    def to_sse(self) -> dict[str, str]:
        body = {"seq": self.seq, **self.payload}
        return {
            "event": self.type,
            "data": json.dumps(body, ensure_ascii=False, default=str),
        }


class Emitter(Protocol):
    """Sink the agent loop writes progress into."""

    async def emit(self, event_type: str, **payload: Any) -> None: ...


class EventBus:
    """Fan-out of run events to any number of live SSE subscribers.

    Subscribers register a queue; the producer never blocks on a slow reader because each
    queue is bounded and drops the oldest delta when full.
    """

    def __init__(self, max_queue: int = 256) -> None:
        self._queues: dict[uuid.UUID, set[asyncio.Queue[RunEvent | None]]] = {}
        self._closed: set[uuid.UUID] = set()
        self._max_queue = max_queue

    def has_subscribers(self, run_id: uuid.UUID) -> bool:
        return bool(self._queues.get(run_id))

    def open(self, run_id: uuid.UUID) -> None:
        """Clear the closed flag when a run (re)starts."""
        self._closed.discard(run_id)

    def is_closed(self, run_id: uuid.UUID) -> bool:
        return run_id in self._closed

    async def publish(self, run_id: uuid.UUID, event: RunEvent) -> None:
        for queue in list(self._queues.get(run_id, ())):
            if queue.full():
                # Drop the oldest delta rather than blocking the producer: a slow reader must
                # never stall an agent run.
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            queue.put_nowait(event)

    def close(self, run_id: uuid.UUID) -> None:
        self._closed.add(run_id)
        for queue in list(self._queues.get(run_id, ())):
            # A full queue means the reader is behind. Make room for the sentinel anyway: if
            # it could not be enqueued the subscriber would wait forever on a run that is
            # already over.
            if queue.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            queue.put_nowait(None)

    async def subscribe(self, run_id: uuid.UUID) -> AsyncIterator[RunEvent]:
        # The closed check and the registration below are deliberately free of awaits: with
        # both happening inside one event-loop turn, a concurrent close() either lands before
        # the check (we return immediately) or after registration (we get the sentinel).
        # Anything else would leave a late subscriber waiting on a queue nobody will feed.
        if run_id in self._closed:
            return
        queue: asyncio.Queue[RunEvent | None] = asyncio.Queue(maxsize=self._max_queue)
        self._queues.setdefault(run_id, set()).add(queue)
        try:
            while True:
                event = await queue.get()
                if event is None:
                    return
                yield event
        finally:
            subscribers = self._queues.get(run_id)
            if subscribers is not None:
                subscribers.discard(queue)
                if not subscribers:
                    self._queues.pop(run_id, None)


bus = EventBus()
