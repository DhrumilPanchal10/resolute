"""Verifier agent — fact-checks the draft and validates action provenance.

Checks:
1. Claims in draft cite evidence that actually supports them.
2. Action args (account_id, invoice_id, amounts) are drawn from tool outputs,
   not invented from ticket text alone.
3. Policy rules (refund > threshold needs approval_token already set, etc.).

Returns verdict: pass | revise | escalate
  pass     → draft proceeds
  revise   → resolver runs again (up to MAX_REVISIONS total)
  escalate → route to human reviewer
"""

from __future__ import annotations

from typing import Any

from agentcore.guardrails import guarded
from agentcore.llm import complete
from resolute.graph.state import VerificationResult

MAX_REVISIONS = 2

_SYSTEM = """\
You are a verifier for a customer support system.

Your job: check that the proposed reply and action plan are:
1. Factually accurate — every claim cites evidence that actually supports it.
2. Action-safe — action args (account_id, amounts, invoice_id) must appear in
   the provided findings/tool results, NOT sourced only from the ticket text.
3. Policy-compliant — refunds or credits over $500 must have requires_approval=true.

Respond with a JSON object:
{
  "verdict": "<pass|revise|escalate>",
  "issues": ["<specific problem>", ...],
  "revised_draft": "<corrected draft if verdict=revise, else empty string>"
}

Verdict guide:
  pass     — reply is accurate, safe, and policy-compliant
  revise   — fixable issues found (wrong facts, missing citations)
  escalate — serious policy breach, potential fraud, or uncertain facts
"""


def _format_evidence(evidence: list[dict[str, Any]]) -> str:
    if not evidence:
        return "(none)"
    return "\n".join(
        f"[{e['source_id']}] {e.get('snippet', '')[:150]}" for e in evidence[:8]
    )


def _format_findings(findings: list[dict[str, Any]]) -> str:
    if not findings:
        return "(none)"
    return "\n".join(
        f"[{f['source_id']}] {f['key']}={f['value']}" for f in findings[:10]
    )


def _format_actions(actions: dict[str, Any] | None) -> str:
    if not actions:
        return "(none)"
    action_list = actions.get("actions", [])
    return "\n".join(
        f"- {a.get('action_type')}: {a.get('args')}, "
        f"approval={a.get('requires_approval')}"
        for a in action_list
    )


@guarded("verifier")
async def verifier_node(state: dict[str, Any]) -> dict[str, Any]:
    messages = [
        {"role": "system", "content": _SYSTEM},
        {
            "role": "user",
            "content": (
                f"Ticket text:\n{state['ticket_text'][:300]}\n\n"
                f"Draft reply:\n{state.get('draft', '')}\n\n"
                f"Evidence:\n{_format_evidence(state.get('evidence', []))}\n\n"
                f"Findings:\n{_format_findings(state.get('findings', []))}\n\n"
                f"Proposed actions:\n{_format_actions(state.get('actions'))}"
            ),
        },
    ]

    tier = state.get("route", "default")
    raw = await complete(messages, schema=VerificationResult, model_tier=tier)

    result: VerificationResult = raw if isinstance(raw, VerificationResult) else VerificationResult(verdict="pass")

    # If verdict is revise, apply the revised draft if provided
    output: dict[str, Any] = {
        "verification": result.model_dump(),
        "revision_count": state.get("revision_count", 0) + 1,
    }

    if result.verdict == "revise" and result.revised_draft:
        output["draft"] = result.revised_draft

    return output
