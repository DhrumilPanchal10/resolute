"""Ticket endpoints.

POST /tickets          — create + start a ticket run
GET  /tickets/{id}     — current status
GET  /tickets/{id}/stream — SSE stream of node events
POST /tickets/{id}/reply  — customer reply → resumes graph
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from resolute.api.models import ReplyRequest, TicketCreate, TicketStatus
from resolute.graph.state import initial_state

router = APIRouter()


def _runner(request: Request) -> Any:
    return request.app.state.runner


def _store(request: Request) -> Any:
    return request.app.state.store


def _bus(request: Request) -> Any:
    return request.app.state.bus


@router.get("", response_model=list[TicketStatus])
async def list_tickets(request: Request, tenant_id: str = "") -> list[TicketStatus]:
    store = _store(request)
    records = store.list(tenant_id=tenant_id or None)
    result: list[TicketStatus] = []
    for rec in records:
        fs = rec.final_state or {}
        result.append(
            TicketStatus(
                ticket_id=rec.ticket_id,
                tenant_id=rec.tenant_id,
                status=rec.status,
                triage=fs.get("triage"),
                draft=fs.get("draft"),
                final_reply=fs.get("final_reply"),
                findings_count=len(fs.get("findings") or []),
                evidence_count=len(fs.get("evidence") or []),
                errors=list(fs.get("errors") or rec.errors),
                interrupt_payload=rec.interrupt_payload,
            )
        )
    return result


@router.post("", response_model=TicketStatus, status_code=201)
async def create_ticket(body: TicketCreate, request: Request) -> TicketStatus:
    ticket_id = str(uuid.uuid4())
    store = _store(request)
    runner = _runner(request)

    store.create(ticket_id, body.tenant_id)
    state = initial_state(
        ticket_id=ticket_id,
        tenant_id=body.tenant_id,
        user_id=body.user_id,
        ticket_text=body.ticket_text,
        token=body.token,
    )
    runner.start(ticket_id, state)

    return TicketStatus(
        ticket_id=ticket_id,
        tenant_id=body.tenant_id,
        status="running",
    )


@router.get("/{ticket_id}", response_model=TicketStatus)
async def get_ticket(ticket_id: str, request: Request) -> TicketStatus:
    store = _store(request)
    rec = store.get(ticket_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="ticket not found")

    fs = rec.final_state or {}
    triage = fs.get("triage")
    errors = list(fs.get("errors") or rec.errors)

    return TicketStatus(
        ticket_id=ticket_id,
        tenant_id=rec.tenant_id,
        status=rec.status,
        triage=triage,
        draft=fs.get("draft"),
        final_reply=fs.get("final_reply"),
        findings_count=len(fs.get("findings") or []),
        evidence_count=len(fs.get("evidence") or []),
        errors=errors,
        interrupt_payload=rec.interrupt_payload,
    )


@router.get("/{ticket_id}/stream")
async def stream_ticket(ticket_id: str, request: Request) -> StreamingResponse:
    store = _store(request)
    if store.get(ticket_id) is None:
        raise HTTPException(status_code=404, detail="ticket not found")

    bus = _bus(request)

    async def _sse() -> AsyncGenerator[str, None]:
        async for event in bus.subscribe(ticket_id):
            yield f"data: {json.dumps(event)}\n\n"
        yield "data: {\"type\": \"done\"}\n\n"

    return StreamingResponse(
        _sse(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{ticket_id}/reply", response_model=TicketStatus)
async def customer_reply(
    ticket_id: str, body: ReplyRequest, request: Request
) -> TicketStatus:
    store = _store(request)
    rec = store.get(ticket_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="ticket not found")
    if rec.status != "interrupted":
        raise HTTPException(
            status_code=409, detail=f"ticket status is '{rec.status}', not interrupted"
        )

    interrupt_payload = rec.interrupt_payload or {}
    if interrupt_payload.get("type") != "awaiting_customer_reply":
        raise HTTPException(
            status_code=409,
            detail="ticket is not awaiting a customer reply",
        )

    runner = _runner(request)
    runner.resume(ticket_id, {"text": body.text})

    return TicketStatus(
        ticket_id=ticket_id,
        tenant_id=rec.tenant_id,
        status="running",
    )
