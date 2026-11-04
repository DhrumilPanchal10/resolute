"""Supervisor — routing functions for the LangGraph conditional edges.

Each function takes state and returns a string (next node name) or a list of
Send objects for fan-out.  These are pure routing decisions; no LLM calls.
"""

from __future__ import annotations

from typing import Any

from langgraph.types import Send

from resolute.graph.agents.verifier import MAX_REVISIONS


def route_after_triage(state: dict[str, Any]) -> str | list[Send]:
    """Exit early for abusive/out-of-scope/injection tickets; else fan out."""
    triage = state.get("triage") or {}
    if triage.get("out_of_scope") or triage.get("injection_risk"):
        return "exit_to_human"
    return [Send("knowledge", state), Send("investigator", state)]


def route_after_verification(state: dict[str, Any]) -> str:
    """Route to send / revise / escalate based on verifier verdict."""
    verification = state.get("verification") or {}
    verdict = verification.get("verdict", "pass")
    revision_count = state.get("revision_count", 0)

    if verdict == "pass":
        actions = state.get("actions") or {}
        needs_approval = any(
            a.get("requires_approval") for a in actions.get("actions", [])
        )
        if needs_approval:
            return "approval_interrupt"
        return "send_reply"

    if verdict == "revise" and revision_count < MAX_REVISIONS:
        return "resolver"

    # revise but exhausted OR escalate
    return "escalate"
