"""SSE event bus — fan-out of graph node events to HTTP subscribers.

Pattern:
  - Each ticket has a list of subscriber queues (one per open SSE connection).
  - Past events are replayed to late-connecting clients from the in-memory log.
  - A sentinel `None` value closes the stream.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncGenerator
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self._queues: dict[str, list[asyncio.Queue[dict[str, Any] | None]]] = (
            defaultdict(list)
        )
        self._logs: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._closed: set[str] = set()

    async def emit(self, ticket_id: str, event: dict[str, Any]) -> None:
        """Append event to the log and push to all active subscribers."""
        self._logs[ticket_id].append(event)
        for q in list(self._queues[ticket_id]):
            await q.put(event)

    async def close(self, ticket_id: str) -> None:
        """Signal end-of-stream to all subscribers."""
        self._closed.add(ticket_id)
        for q in list(self._queues[ticket_id]):
            await q.put(None)

    async def subscribe(
        self, ticket_id: str
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Async generator — yields all past events then live ones until closed."""
        q: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self._queues[ticket_id].append(q)
        try:
            # Replay past events first
            for past_event in list(self._logs[ticket_id]):
                yield past_event
            # Already closed before we subscribed — done
            if ticket_id in self._closed:
                return
            # Live events
            while True:
                event = await q.get()
                if event is None:
                    break
                yield event
        finally:
            queues = self._queues[ticket_id]
            if q in queues:
                queues.remove(q)
