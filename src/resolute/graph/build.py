"""LangGraph graph construction for the Resolute support pipeline.

Topology
--------
  START
    │
  triage ──(out_of_scope/injection)──> exit_to_human ──> END
    │
    ▼  (fan-out via Send — both run in parallel)
  knowledge ┐
  investigator ┘
    │
    ▼
  join ──> resolver ──> verifier
                           │
              ┌────────────┼────────────────┐
              ▼            ▼                ▼
          revise    approval_interrupt   send_reply / escalate
          (loop)         │                  │
                      interrupt()          END
                      resume ──────────> execute_actions ──> END

Fan-out
-------
`route_after_triage` returns a list[Send] for the normal path, launching
knowledge and investigator as parallel tasks.  Their outputs merge via
`Annotated[list, operator.add]` reducers defined in `ResoluteState`.

Checkpointing
-------------
Production: `AsyncPostgresSaver` from `langgraph-checkpoint-postgres`.
Tests / demo: `MemorySaver` (in-process, no Postgres needed).

Usage
-----
    # Build with in-memory checkpointer (tests / demo)
    graph = build_graph()

    # Build with Postgres checkpointer
    async with get_pg_checkpointer() as checkpointer:
        graph = build_graph(checkpointer=checkpointer)

    # Run one ticket
    config = {"configurable": {"thread_id": "ticket-001"}}
    result = await graph.ainvoke(state_dict, config=config)

CLI demo (invoked by `make demo`):
    python -m resolute.graph.build --demo
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from resolute.graph.agents.investigator import investigator_node
from resolute.graph.agents.knowledge import knowledge_node
from resolute.graph.agents.resolver import resolver_node
from resolute.graph.agents.supervisor import route_after_triage, route_after_verification
from resolute.graph.agents.triage import triage_node
from resolute.graph.agents.verifier import verifier_node
from resolute.graph.state import ResoluteState, initial_state

# ---------------------------------------------------------------------------
# Terminal / helper nodes
# ---------------------------------------------------------------------------


async def exit_to_human_node(state: dict[str, Any]) -> dict[str, Any]:
    """Route abusive/OOS/injection tickets directly to a human queue."""
    triage = state.get("triage") or {}
    reason = "out_of_scope" if triage.get("out_of_scope") else "injection_risk"
    return {
        "final_reply": f"[ESCALATED:{reason}] Ticket routed to human reviewer.",
        "errors": [f"auto-escalated: {reason}"],
    }


async def join_node(state: dict[str, Any]) -> dict[str, Any]:
    """No-op join — LangGraph merges fan-out outputs via reducers automatically."""
    return {}


async def approval_interrupt_node(state: dict[str, Any]) -> dict[str, Any]:
    """Pause for human approval of high-value actions."""
    actions = state.get("actions") or {}
    pending = [
        a for a in actions.get("actions", []) if a.get("requires_approval")
    ]
    decision = interrupt(
        {
            "type": "approval_required",
            "ticket_id": state["ticket_id"],
            "pending_actions": pending,
            "draft": state.get("draft", ""),
        }
    )
    # Resume: decision = {"approved": True/False, "edited_draft": "..."}
    if isinstance(decision, dict) and not decision.get("approved", True):
        return {"final_reply": "[REJECTED BY REVIEWER]", "errors": ["approval rejected"]}
    edited = decision.get("edited_draft", "") if isinstance(decision, dict) else ""
    if edited:
        return {"draft": edited}
    return {}


async def send_reply_node(state: dict[str, Any]) -> dict[str, Any]:
    """Finalise the reply (in production: send via ticket system)."""
    return {"final_reply": state.get("draft", "")}


async def escalate_node(state: dict[str, Any]) -> dict[str, Any]:
    """Escalate to human reviewer after exhausting revision budget."""
    return {
        "final_reply": "[ESCALATED] Ticket requires human review.",
        "errors": ["escalated after revision limit"],
    }


async def execute_actions_node(state: dict[str, Any]) -> dict[str, Any]:
    """Execute approved actions (Stripe, GitHub, etc.) — stub for Phase 6."""
    # In production: dispatch to MCP tool servers based on actions list.
    return {}


async def wait_for_customer_reply_node(state: dict[str, Any]) -> dict[str, Any]:
    """Interrupt after a reply is sent; resume when the customer replies back.

    Resume value: {"text": "<customer reply text>"}
    """
    reply = interrupt(
        {
            "type": "awaiting_customer_reply",
            "ticket_id": state["ticket_id"],
            "final_reply": state.get("final_reply", ""),
        }
    )
    text = reply.get("text", "") if isinstance(reply, dict) else str(reply)
    return {
        "ticket_text": text,
        "triage": None,
        "draft": None,
        "actions": None,
        "verification": None,
        "revision_count": 0,
    }


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build_graph(checkpointer: Any = None) -> Any:
    """Build and compile the support-resolution StateGraph.

    Args:
        checkpointer: LangGraph checkpointer.  Defaults to MemorySaver.
    """
    if checkpointer is None:
        checkpointer = MemorySaver()

    sg: Any = StateGraph(ResoluteState)

    # Register nodes
    sg.add_node("triage", triage_node)
    sg.add_node("knowledge", knowledge_node)
    sg.add_node("investigator", investigator_node)
    sg.add_node("join", join_node)
    sg.add_node("resolver", resolver_node)
    sg.add_node("verifier", verifier_node)
    sg.add_node("exit_to_human", exit_to_human_node)
    sg.add_node("approval_interrupt", approval_interrupt_node)
    sg.add_node("send_reply", send_reply_node)
    sg.add_node("escalate", escalate_node)
    sg.add_node("execute_actions", execute_actions_node)
    sg.add_node("wait_for_customer_reply", wait_for_customer_reply_node)

    # START → triage
    sg.add_edge(START, "triage")

    # triage → (exit_to_human | Send(knowledge) + Send(investigator))
    # route_after_triage returns "exit_to_human" (str) or list[Send] for fan-out
    sg.add_conditional_edges(
        "triage",
        route_after_triage,
        {"exit_to_human": "exit_to_human"},
    )
    sg.add_edge("exit_to_human", END)

    # Fan-out convergence: both parallel nodes → join → resolver
    sg.add_edge("knowledge", "join")
    sg.add_edge("investigator", "join")
    sg.add_edge("join", "resolver")
    sg.add_edge("resolver", "verifier")

    sg.add_conditional_edges(
        "verifier",
        route_after_verification,
        {
            "send_reply": "send_reply",
            "resolver": "resolver",
            "approval_interrupt": "approval_interrupt",
            "escalate": "escalate",
        },
    )
    sg.add_edge("send_reply", "execute_actions")
    sg.add_edge("approval_interrupt", "execute_actions")
    sg.add_edge("execute_actions", "wait_for_customer_reply")
    # wait_for_customer_reply loops back to triage for multi-turn conversations
    sg.add_edge("wait_for_customer_reply", "triage")
    sg.add_edge("escalate", END)

    return sg.compile(checkpointer=checkpointer, interrupt_before=["approval_interrupt"])


# ---------------------------------------------------------------------------
# Postgres checkpointer helper
# ---------------------------------------------------------------------------


async def get_pg_checkpointer(database_url: str | None = None) -> Any:
    """Return an async context manager yielding an AsyncPostgresSaver."""
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    from resolute.config import settings

    url = database_url or settings.database_url
    # Convert SQLAlchemy DSN to plain psycopg DSN
    conn_str = url.replace("postgresql+psycopg://", "postgresql://")
    return AsyncPostgresSaver.from_conn_string(conn_str)


# ---------------------------------------------------------------------------
# Demo mode (invoked by `make demo`)
# ---------------------------------------------------------------------------

DEMO_TICKETS = [
    {
        "ticket_id": "demo-001",
        "tenant_id": "tenant-demo",
        "user_id": "user-demo",
        "ticket_text": (
            "Hi, I was charged twice for my Pro plan subscription last month. "
            "Invoice INV-2024-001 shows $199 but I see two charges on my card. "
            "Please refund the duplicate. My account ID is acct-demo-001."
        ),
    },
    {
        "ticket_id": "demo-002",
        "tenant_id": "tenant-demo",
        "user_id": "user-demo",
        "ticket_text": (
            "I can't log in since the last deploy. Getting 401 Unauthorized "
            "every time I try to authenticate with my OAuth token. "
            "This is blocking our entire team."
        ),
    },
    {
        "ticket_id": "demo-003",
        "tenant_id": "tenant-demo",
        "user_id": "user-demo",
        "ticket_text": (
            "How do I upgrade from Starter to Pro plan? "
            "What features do I get and how is billing handled?"
        ),
    },
]


async def _run_demo_ticket(
    graph: Any, ticket: dict[str, Any], *, verbose: bool = True
) -> Any:
    state = initial_state(**ticket)
    config = {"configurable": {"thread_id": ticket["ticket_id"]}}
    result = await graph.ainvoke(state, config=config)
    if verbose:
        triage = result.get("triage") or {}
        print(
            f"\n[{ticket['ticket_id']}] {triage.get('category','?')} / "
            f"{triage.get('severity','?')} → {str(result.get('final_reply',''))[:80]}..."
        )
    return result


async def _demo_main() -> None:
    from agentcore.llm import _set_complete_fn
    from resolute.graph.state import (
        ActionPlan,
        ResolverOutput,
        TriageResult,
        VerificationResult,
    )

    # Deterministic canned responses for offline demo
    _call_count: list[int] = [0]

    _TRIAGE_RESPONSES = [
        TriageResult(
            category="billing",
            severity="high",
            tier="default",
            injection_risk=False,
            out_of_scope=False,
            summary="Customer reports duplicate charge on Pro plan subscription.",
        ),
        TriageResult(
            category="auth",
            severity="critical",
            tier="default",
            injection_risk=False,
            out_of_scope=False,
            summary="OAuth authentication failing after recent deployment.",
        ),
        TriageResult(
            category="billing",
            severity="low",
            tier="small",
            injection_risk=False,
            out_of_scope=False,
            summary="Customer asking about plan upgrade options.",
        ),
    ]

    _ticket_index: list[int] = [0]

    async def _fake_complete(
        messages: list[dict[str, Any]],
        schema: Any = None,
        model_tier: str = "small",
        **_: Any,
    ) -> Any:
        _call_count[0] += 1
        idx = _ticket_index[0]

        if schema is TriageResult:
            return _TRIAGE_RESPONSES[idx % len(_TRIAGE_RESPONSES)]

        if schema is ResolverOutput:
            return ResolverOutput(
                draft=(
                    "Thank you for reaching out. We've investigated your issue "
                    "[offline-placeholder] and will resolve it promptly."
                ),
                evidence_ids=["offline-placeholder"],
                action_plan=ActionPlan(actions=[]),
            )

        if schema is VerificationResult:
            return VerificationResult(verdict="pass", issues=[])

        # Distinguish knowledge (expects JSON array) from investigator (expects done JSON)
        system_msg = messages[0].get("content", "") if messages else ""
        if "knowledge retrieval" in system_msg:
            return '[{"source_id":"offline-placeholder","source_type":"docs","heading":"FAQ","snippet":"No live data available offline.","relevance":0.8}]'
        # Investigator ReAct loop — signal done immediately
        return '{"done": true, "findings": []}'

    _set_complete_fn(_fake_complete)

    try:
        graph = build_graph()
        print("Resolute demo — running 3 tickets offline\n" + "=" * 50)

        for i, ticket in enumerate(DEMO_TICKETS):
            _ticket_index[0] = i
            await _run_demo_ticket(graph, ticket)

        print("\n" + "=" * 50)
        print(f"Done — {_call_count[0]} LLM calls (all canned, no API keys needed).")
    finally:
        _set_complete_fn(None)


if __name__ == "__main__":
    if "--demo" in sys.argv:
        asyncio.run(_demo_main())
    else:
        print("Usage: python -m resolute.graph.build --demo")
        sys.exit(1)
