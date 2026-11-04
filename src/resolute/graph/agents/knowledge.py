"""Knowledge agent — retrieves documentation and episodic memory.

Calls the docs MCP server and the episodic memory store, then uses the LLM
to rank and annotate the best evidence for the resolver.

Outputs (appended to state):
  evidence: list[EvidenceItem]  — doc chunks + memory hits ranked by relevance
"""

from __future__ import annotations

from typing import Any

from agentcore.guardrails import guarded
from agentcore.llm import complete
from resolute.graph.state import EvidenceItem

_SYSTEM = """\
You are a knowledge retrieval assistant.  Given a support ticket summary and \
raw retrieved passages, select the most relevant evidence items and return them \
as a JSON array.

Each item:
{
  "source_id": "<doc_id or memory_id>",
  "source_type": "<docs|memory>",
  "heading": "<heading path>",
  "snippet": "<≤300 char excerpt>",
  "relevance": <0.0-1.0>
}

Return ONLY the JSON array, ordered by relevance descending, max 8 items.
"""


@guarded("knowledge")
async def knowledge_node(state: dict[str, Any]) -> dict[str, Any]:
    triage = state.get("triage") or {}
    summary = triage.get("summary", state["ticket_text"][:200])

    # Collect retrieved passages from the docs MCP store (injected via state)
    docs_store = state.get("_docs_store")
    passages: list[dict[str, Any]] = []

    if docs_store is not None:
        from resolute.mcp_servers.docs import make_search_docs_tool

        tool = make_search_docs_tool(docs_store)
        try:
            hits = await tool(
                token=state.get("token", ""),
                query=summary,
                tenant_id=state["tenant_id"],
                user_roles=["support_engineer"],
                k=8,
                rerank=False,
            )
            for h in hits:
                passages.append(
                    {
                        "source_id": h["doc_id"],
                        "source_type": "docs",
                        "heading": h.get("heading_path", ""),
                        "snippet": h["text"][:300],
                    }
                )
        except Exception as exc:  # noqa: BLE001
            return {"errors": [f"knowledge/docs: {exc}"]}

    if not passages:
        # No docs store injected (offline unit test without store)
        passages = [
            {
                "source_id": "offline-placeholder",
                "source_type": "docs",
                "heading": "N/A",
                "snippet": "No docs store available in this environment.",
            }
        ]

    passages_text = "\n".join(
        f"[{p['source_id']}] {p['heading']}: {p['snippet']}" for p in passages
    )
    messages = [
        {"role": "system", "content": _SYSTEM},
        {
            "role": "user",
            "content": (
                f"Ticket summary: {summary}\n\n"
                f"Retrieved passages:\n{passages_text}"
            ),
        },
    ]

    tier = state.get("route", "small")
    raw = await complete(messages, model_tier=tier)

    import json  # noqa: PLC0415

    items: list[dict[str, Any]] = []
    try:
        parsed = json.loads(raw if isinstance(raw, str) else "[]")
        for item in parsed[:8]:
            items.append(
                EvidenceItem(
                    source_id=item.get("source_id", ""),
                    source_type=item.get("source_type", "docs"),
                    heading=item.get("heading", ""),
                    snippet=item.get("snippet", "")[:300],
                    relevance=float(item.get("relevance", 0.5)),
                ).model_dump()
            )
    except (json.JSONDecodeError, ValueError):
        pass

    return {"evidence": items}
