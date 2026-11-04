"""Approval endpoint.

POST /approvals/{ticket_id}
  Approve or reject a pending high-value action, optionally with an edited draft.
  Resumes the paused graph via Command(resume=...).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from resolute.api.models import ApprovalRequest, TicketStatus

router = APIRouter()


def _runner(request: Request) -> Any:
    return request.app.state.runner


def _store(request: Request) -> Any:
    return request.app.state.store


@router.post("/{ticket_id}", response_model=TicketStatus)
async def approve_ticket(
    ticket_id: str, body: ApprovalRequest, request: Request
) -> TicketStatus:
    store = _store(request)
    rec = store.get(ticket_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="ticket not found")
    if rec.status != "interrupted":
        raise HTTPException(
            status_code=409,
            detail=f"ticket status is '{rec.status}', not interrupted",
        )

    interrupt_payload = rec.interrupt_payload or {}
    if interrupt_payload.get("type") != "approval_required":
        raise HTTPException(
            status_code=409,
            detail="ticket is not awaiting an approval",
        )

    if body.action not in ("approve", "reject"):
        raise HTTPException(
            status_code=422, detail="action must be 'approve' or 'reject'"
        )

    resume_value: dict[str, Any] = {
        "approved": body.action == "approve",
        "edited_draft": body.edited_draft,
    }

    runner = _runner(request)
    runner.resume(ticket_id, resume_value)

    return TicketStatus(
        ticket_id=ticket_id,
        tenant_id=rec.tenant_id,
        status="running",
    )
