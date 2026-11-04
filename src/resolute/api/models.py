"""Pydantic request/response models for the Resolute API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TicketCreate(BaseModel):
    tenant_id: str
    user_id: str
    ticket_text: str
    token: str = ""


class TicketStatus(BaseModel):
    ticket_id: str
    tenant_id: str
    status: str = Field(description="pending | running | interrupted | complete | failed")
    triage: dict[str, Any] | None = None
    draft: str | None = None
    final_reply: str | None = None
    findings_count: int = 0
    evidence_count: int = 0
    errors: list[str] = Field(default_factory=list)
    interrupt_payload: dict[str, Any] | None = None


class ApprovalRequest(BaseModel):
    action: str = Field(description="approve | reject")
    edited_draft: str = ""


class ReplyRequest(BaseModel):
    text: str


class NodeEvent(BaseModel):
    type: str
    node: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    ticket_id: str = ""
