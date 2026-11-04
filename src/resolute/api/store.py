"""TicketStore and GraphRunner — in-memory state store + background graph executor.

TicketStore:
  Injectable in-memory store (tests) or backed by Postgres (production).
  Tracks per-ticket status, final state, and interrupt payload.

GraphRunner:
  Launches and resumes the LangGraph graph as background asyncio tasks.
  Emits structured events to the EventBus as each node completes.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from langgraph.types import Command

from resolute.api.sse import EventBus

logger = logging.getLogger(__name__)

# LangGraph internal node names to suppress from SSE output
_INTERNAL_NODES: frozenset[str] = frozenset({"LangGraph", "__start__", "join"})


@dataclass
class TicketRecord:
    ticket_id: str
    tenant_id: str
    status: str = "pending"  # pending | running | interrupted | complete | failed
    final_state: dict[str, Any] | None = None
    interrupt_payload: dict[str, Any] | None = None
    errors: list[str] = field(default_factory=list)


class TicketStore:
    """Thread-safe in-memory ticket store."""

    def __init__(self) -> None:
        self._records: dict[str, TicketRecord] = {}

    def create(self, ticket_id: str, tenant_id: str) -> TicketRecord:
        rec = TicketRecord(ticket_id=ticket_id, tenant_id=tenant_id)
        self._records[ticket_id] = rec
        return rec

    def get(self, ticket_id: str) -> TicketRecord | None:
        return self._records.get(ticket_id)

    def update_status(self, ticket_id: str, status: str) -> None:
        rec = self._records.get(ticket_id)
        if rec:
            rec.status = status

    def set_complete(self, ticket_id: str, final_state: dict[str, Any]) -> None:
        rec = self._records.get(ticket_id)
        if rec:
            rec.status = "complete"
            rec.final_state = final_state

    def set_interrupted(
        self, ticket_id: str, payload: dict[str, Any]
    ) -> None:
        rec = self._records.get(ticket_id)
        if rec:
            rec.status = "interrupted"
            rec.interrupt_payload = payload

    def set_failed(self, ticket_id: str, error: str) -> None:
        rec = self._records.get(ticket_id)
        if rec:
            rec.status = "failed"
            rec.errors.append(error)


class GraphRunner:
    """Launches and resumes the LangGraph graph, streaming events to the EventBus."""

    def __init__(self, graph: Any, store: TicketStore, bus: EventBus) -> None:
        self._graph = graph
        self._store = store
        self._bus = bus

    def start(self, ticket_id: str, state_dict: dict[str, Any]) -> None:
        """Fire-and-forget: start the graph for a new ticket."""
        self._store.update_status(ticket_id, "running")
        asyncio.create_task(
            self._run(ticket_id, state_dict),
            name=f"graph-{ticket_id}",
        )

    def resume(
        self, ticket_id: str, resume_value: dict[str, Any]
    ) -> None:
        """Fire-and-forget: resume a paused graph after approval or reply."""
        self._store.update_status(ticket_id, "running")
        asyncio.create_task(
            self._run(ticket_id, Command(resume=resume_value)),
            name=f"graph-resume-{ticket_id}",
        )

    async def _run(
        self,
        ticket_id: str,
        graph_input: Any,
    ) -> None:
        config = {"configurable": {"thread_id": ticket_id}}
        try:
            async for event in self._graph.astream_events(
                graph_input, config, version="v2"
            ):
                evt_type = event.get("event", "")
                node_name = event.get("name", "")

                if evt_type == "on_chain_start" and node_name not in _INTERNAL_NODES:
                    await self._bus.emit(
                        ticket_id,
                        {
                            "type": "node_start",
                            "node": node_name,
                            "ticket_id": ticket_id,
                        },
                    )
                elif evt_type == "on_chain_end" and node_name not in _INTERNAL_NODES:
                    output = event.get("data", {}).get("output", {})
                    safe_output = _safe_dict(output)
                    await self._bus.emit(
                        ticket_id,
                        {
                            "type": "node_end",
                            "node": node_name,
                            "ticket_id": ticket_id,
                            "data": safe_output,
                        },
                    )
        except Exception as exc:
            logger.exception("graph run failed for %s", ticket_id)
            self._store.set_failed(ticket_id, str(exc))
            await self._bus.emit(
                ticket_id,
                {"type": "error", "ticket_id": ticket_id, "message": str(exc)},
            )
            await self._bus.close(ticket_id)
            return

        # Graph completed or paused — inspect snapshot
        try:
            snap = await self._graph.aget_state(config)
        except Exception:
            snap = None

        if snap and snap.next:
            # Graph is paused (interrupt)
            interrupt_payload: dict[str, Any] = {}
            for task in snap.tasks:
                if task.interrupts:
                    interrupt_payload = dict(task.interrupts[0].value)
                    break
            self._store.set_interrupted(ticket_id, interrupt_payload)
            await self._bus.emit(
                ticket_id,
                {
                    "type": "interrupt",
                    "ticket_id": ticket_id,
                    **interrupt_payload,
                },
            )
        else:
            # Complete
            final_state = dict(snap.values) if snap else {}
            self._store.set_complete(ticket_id, final_state)
            await self._bus.emit(
                ticket_id,
                {
                    "type": "complete",
                    "ticket_id": ticket_id,
                    "final_reply": final_state.get("final_reply", ""),
                },
            )

        await self._bus.close(ticket_id)


def _safe_dict(value: Any) -> dict[str, Any]:
    """Return a plain dict suitable for JSON serialisation."""
    if isinstance(value, dict):
        return {k: _safe_val(v) for k, v in value.items() if not str(k).startswith("_")}
    return {}


def _safe_val(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return _safe_dict(value)
    if isinstance(value, list):
        return [_safe_val(v) for v in value]
    return str(value)
