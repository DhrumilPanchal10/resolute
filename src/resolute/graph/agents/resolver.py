"""Resolver agent — drafts a customer reply and proposes an action plan.

Every factual claim in the draft must be tagged with an evidence/finding ID.
The resolver also decides what follow-up actions to take (credits, refunds,
GitHub issues, escalation).

Outputs:
  draft:   str                    — customer-facing reply
  actions: dict (ActionPlan)      — proposed actions
"""

from __future__ import annotations

from typing import Any

from agentcore.guardrails import guarded
from agentcore.llm import complete
from resolute.graph.state import ActionPlan, ResolverOutput

_SYSTEM = """\
You are a customer support resolver.  Using the ticket, evidence, and \
findings provided, write a helpful reply and propose any follow-up actions.

Rules:
1. Every factual claim must cite at least one evidence or finding source_id
   using [source_id] inline notation.
2. Be empathetic and clear.  Keep the reply under 200 words.
3. Only propose actions that are directly supported by the findings.
4. Available action types: issue_credit | refund_invoice | create_github_issue |
   escalate | reply_only
5. If a refund or credit > $500, set requires_approval = true.

Respond with a JSON object:
{
  "draft": "<reply text with [source_id] citations>",
  "evidence_ids": ["<id>", ...],
  "action_plan": {
    "actions": [
      {
        "action_type": "<type>",
        "args": {<key: value>},
        "requires_approval": <bool>,
        "approval_reason": "<why approval needed>"
      }
    ]
  }
}
"""


def _format_evidence(evidence: list[dict[str, Any]]) -> str:
    if not evidence:
        return "(none)"
    return "\n".join(
        f"[{e['source_id']}] {e.get('heading', '')} — {e.get('snippet', '')[:200]}"
        for e in evidence[:8]
    )


def _format_findings(findings: list[dict[str, Any]]) -> str:
    if not findings:
        return "(none)"
    return "\n".join(
        f"[{f['source_id']}] {f['key']} = {f['value']}" for f in findings[:10]
    )


@guarded("resolver")
async def resolver_node(state: dict[str, Any]) -> dict[str, Any]:
    triage = state.get("triage") or {}

    # Short-term memory compaction: if previous draft exists (revision loop),
    # prepend it so the resolver sees what it already wrote
    prior_note = ""
    if state.get("draft") and state.get("revision_count", 0) > 0:
        issues = []
        verification = state.get("verification") or {}
        issues = verification.get("issues", [])
        if issues:
            prior_note = (
                "\n\nPrevious draft was rejected.  Issues to fix:\n"
                + "\n".join(f"- {i}" for i in issues)
                + f"\n\nPrevious draft:\n{state['draft']}\n"
            )

    messages = [
        {"role": "system", "content": _SYSTEM},
        {
            "role": "user",
            "content": (
                f"Ticket #{state['ticket_id']} [{triage.get('category', 'other')}]:\n"
                f"{state['ticket_text']}\n\n"
                f"Evidence:\n{_format_evidence(state.get('evidence', []))}\n\n"
                f"Findings:\n{_format_findings(state.get('findings', []))}"
                f"{prior_note}"
            ),
        },
    ]

    tier = state.get("route", "default")
    raw = await complete(messages, schema=ResolverOutput, model_tier=tier)

    result: ResolverOutput
    if isinstance(raw, ResolverOutput):
        result = raw
    else:
        result = ResolverOutput(draft=str(raw), action_plan=ActionPlan())

    return {
        "draft": result.draft,
        "actions": result.action_plan.model_dump(),
    }
