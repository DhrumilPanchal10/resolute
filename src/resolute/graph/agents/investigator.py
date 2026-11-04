"""Investigator agent — bounded ReAct loop over accounts, logs, GitHub.

The agent runs at most MAX_TOOL_CALLS tool calls, then synthesises findings.
Each tool call is recorded in state["tool_calls"].

Outputs (appended to state):
  findings: list[Finding]  — factual findings with source IDs
  tool_calls: list[dict]   — full record of calls made
"""

from __future__ import annotations

import contextlib
import json
from typing import Any

from agentcore.guardrails import guarded
from agentcore.llm import complete
from resolute.graph.state import Finding

MAX_TOOL_CALLS = 6

_SYSTEM = """\
You are an investigator agent for a customer support platform.  Your job is to \
gather factual evidence by calling the available tools, then produce a \
structured finding list.

Available tools (call by returning JSON in your response):
  get_account(account_id, tenant_id)  — account plan, MRR, creation date
  get_invoices(account_id, tenant_id) — recent invoices
  get_usage(account_id, tenant_id)    — usage stats
  search_logs(account_id, tenant_id, text) — application logs
  search_issues(q)                    — GitHub issues

To call a tool, respond with EXACTLY this JSON (and nothing else):
{"tool": "<tool_name>", "args": {<args>}}

When you have gathered enough information (or hit the tool call limit), respond with:
{"done": true, "findings": [
  {"source_id": "...", "source_type": "...", "key": "...", "value": "..."},
  ...
]}

Base your investigation on the ticket text and triage category.
"""


@guarded("investigator")
async def investigator_node(state: dict[str, Any]) -> dict[str, Any]:
    triage = state.get("triage") or {}
    category = triage.get("category", "other")

    history: list[dict[str, Any]] = [
        {"role": "system", "content": _SYSTEM},
        {
            "role": "user",
            "content": (
                f"Ticket #{state['ticket_id']} [{category}]:\n"
                f"{state['ticket_text']}\n\n"
                f"Account: {state.get('ticket_id', 'unknown')}\n"
                f"Tenant:  {state['tenant_id']}"
            ),
        },
    ]

    tool_calls_made: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    tier = state.get("route", "default")

    for _ in range(MAX_TOOL_CALLS + 1):
        raw = await complete(history, model_tier=tier)
        text = raw if isinstance(raw, str) else ""

        try:
            response = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            break

        # Terminal: agent says done
        if response.get("done"):
            for f in response.get("findings", []):
                with contextlib.suppress(Exception):
                    findings.append(
                        Finding(
                            source_id=str(f.get("source_id", "")),
                            source_type=str(f.get("source_type", "account")),
                            key=str(f.get("key", "")),
                            value=str(f.get("value", "")),
                        ).model_dump()
                    )
            break

        # Tool call: execute and feed result back
        tool_name = response.get("tool", "")
        args = response.get("args", {})

        result = await _dispatch_tool(state, tool_name, args)
        record = {"tool": tool_name, "args": args, "result": result}
        tool_calls_made.append(record)

        history.append({"role": "assistant", "content": text})
        history.append(
            {
                "role": "user",
                "content": f"Tool result for {tool_name}: {json.dumps(result)}",
            }
        )

    return {
        "findings": findings,
        "tool_calls": tool_calls_made,
    }


async def _dispatch_tool(
    state: dict[str, Any], tool_name: str, args: dict[str, Any]
) -> Any:
    """Route tool calls to the appropriate MCP store (injected via state)."""
    token = state.get("token", "")
    tenant_id = state["tenant_id"]
    user_roles = ["support_engineer"]

    if tool_name == "get_account":
        store = state.get("_accounts_store")
        if store is None:
            return {"error": "accounts store not configured"}
        from resolute.mcp_servers.accounts import make_get_account_tool

        tool = make_get_account_tool(store)
        return await tool(
            token=token,
            account_id=args.get("account_id", ""),
            tenant_id=tenant_id,
            user_roles=user_roles,
        )

    if tool_name == "get_invoices":
        store = state.get("_accounts_store")
        if store is None:
            return {"error": "accounts store not configured"}
        from resolute.mcp_servers.accounts import make_get_invoices_tool

        tool = make_get_invoices_tool(store)
        return await tool(
            token=token,
            account_id=args.get("account_id", ""),
            tenant_id=tenant_id,
            user_roles=user_roles,
        )

    if tool_name == "get_usage":
        store = state.get("_accounts_store")
        if store is None:
            return {"error": "accounts store not configured"}
        from resolute.mcp_servers.accounts import make_get_usage_tool

        tool = make_get_usage_tool(store)
        return await tool(
            token=token,
            account_id=args.get("account_id", ""),
            tenant_id=tenant_id,
            user_roles=user_roles,
        )

    if tool_name == "search_logs":
        store = state.get("_logs_store")
        if store is None:
            return {"error": "logs store not configured"}
        from resolute.mcp_servers.logs import make_search_logs_tool

        tool = make_search_logs_tool(store)
        return await tool(
            token=token,
            account_id=args.get("account_id", ""),
            tenant_id=tenant_id,
            user_roles=user_roles,
            text=args.get("text"),
        )

    if tool_name == "search_issues":
        store = state.get("_github_client")
        if store is None:
            return {"error": "github client not configured"}
        from resolute.mcp_servers.github import make_search_issues_tool

        tool = make_search_issues_tool(store)
        return await tool(
            token=token,
            q=args.get("q", ""),
            tenant_id=tenant_id,
            user_roles=user_roles,
        )

    return {"error": f"unknown tool: {tool_name}"}
