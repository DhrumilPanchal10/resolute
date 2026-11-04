"""FastAPI application for the Resolute support-resolution platform.

Endpoints
---------
POST   /tickets                    — create + start a ticket run
GET    /tickets/{id}               — current status
GET    /tickets/{id}/stream        — SSE stream of node events
POST   /tickets/{id}/reply         — customer reply → resumes graph
POST   /approvals/{ticket_id}      — approve/reject a pending action

Usage (local dev)
-----------------
    make up        # starts Postgres + Redis
    uvicorn resolute.api.main:app --reload --port 8000

Offline / test mode
-------------------
    OFFLINE=1  — graph uses MemorySaver; LLM calls use the _complete_fn override.

Factory function
----------------
`create_app(graph, store, bus)` accepts injected dependencies for tests.
When all three are provided, they are attached to `app.state` immediately —
httpx.ASGITransport does not fire lifespan, so injection bypasses it.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from resolute.api.routes_approvals import router as approvals_router
from resolute.api.routes_tickets import router as tickets_router
from resolute.api.sse import EventBus
from resolute.api.store import GraphRunner, TicketStore
from agentcore.telemetry import init_telemetry
from resolute.config import settings
from resolute.graph.build import build_graph


def create_app(
    graph: Any | None = None,
    store: TicketStore | None = None,
    bus: EventBus | None = None,
) -> FastAPI:
    """Create a FastAPI app with optional injected dependencies (for testing).

    When all three deps are provided, they are set on `app.state` immediately so
    that httpx.ASGITransport-based tests (which don't fire lifespan) work correctly.

    Args:
        graph:  Compiled LangGraph graph.  Defaults to build_graph() (MemorySaver).
        store:  TicketStore instance.  Defaults to a fresh TicketStore().
        bus:    EventBus instance.  Defaults to a fresh EventBus().
    """

    @asynccontextmanager
    async def lifespan(application: FastAPI):  # type: ignore[no-untyped-def]
        init_telemetry(
            endpoint=settings.otlp_endpoint,
            langfuse_public=settings.langfuse_public_key,
            langfuse_secret=settings.langfuse_secret_key,
        )
        # Only initialise here when no injected deps (production path).
        if not hasattr(application.state, "store"):
            _graph = build_graph()
            _store = TicketStore()
            _bus = EventBus()
            application.state.graph = _graph
            application.state.store = _store
            application.state.bus = _bus
            application.state.runner = GraphRunner(_graph, _store, _bus)
        yield

    app = FastAPI(
        title="Resolute",
        description="Multi-agent customer support resolution platform",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(tickets_router, prefix="/tickets", tags=["tickets"])
    app.include_router(approvals_router, prefix="/approvals", tags=["approvals"])

    # Set injected deps immediately so httpx ASGI transport works without lifespan
    if graph is not None or store is not None or bus is not None:
        _graph = graph or build_graph()
        _store = store or TicketStore()
        _bus = bus or EventBus()
        app.state.graph = _graph
        app.state.store = _store
        app.state.bus = _bus
        app.state.runner = GraphRunner(_graph, _store, _bus)

    return app


# Module-level app for `uvicorn resolute.api.main:app`
app = create_app()
