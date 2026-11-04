"""Logs MCP server — search_logs over application event logs.

Architecture
------------
LogStore is an injectable data layer.  In production it queries the `logs`
table (migration 002_logs.sql) using `db_session(tenant_id)` with Postgres
full-text search (`to_tsvector` / `@@`).  In unit tests an in-memory
LogStore is passed so no database is needed.

One MCP tool is exposed:

  search_logs(account_id, tenant_id, user_roles, since, level, text, limit)
      Returns log entries filtered by account, time window, severity level,
      and optional full-text query.  Requires logs.read.
      Contractors are denied (logs may contain sensitive operational data).
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from agentcore.audit import AuditLog
from resolute.mcp_servers.base import ToolRisk, mcp_tool

# ---------------------------------------------------------------------------
# LogStore — injectable data layer
# ---------------------------------------------------------------------------

VALID_LEVELS = frozenset({"INFO", "WARN", "ERROR"})


@dataclass
class LogStore:
    """In-memory log store for unit tests.

    Each entry dict must have:
        id, tenant_id, account_id, level, message, occurred_at (ISO string)
    """

    entries: list[dict[str, Any]] = field(default_factory=list)

    def search(
        self,
        account_id: str,
        tenant_id: str,
        since: str | None = None,
        level: str | None = None,
        text: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        since_dt: datetime | None = None
        if since:
            with contextlib.suppress(ValueError):
                since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))

        level_upper = level.upper() if level else None

        results = []
        for entry in self.entries:
            if entry.get("tenant_id") != tenant_id:
                continue
            if entry.get("account_id") != account_id:
                continue
            if level_upper and entry.get("level", "").upper() != level_upper:
                continue
            if since_dt:
                raw = entry.get("occurred_at", "")
                try:
                    occ = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                    if occ < since_dt:
                        continue
                except ValueError:
                    pass
            if text and text.lower() not in (entry.get("message") or "").lower():
                continue
            results.append(entry)
            if len(results) >= limit:
                break

        return results


# ---------------------------------------------------------------------------
# Tool factory
# ---------------------------------------------------------------------------


def make_search_logs_tool(
    store: LogStore,
    audit_log: AuditLog | None = None,
    span_sink: list[Any] | None = None,
) -> Any:
    """Return a guarded search_logs coroutine bound to the given LogStore."""

    @mcp_tool(
        "logs",
        "read",
        risk=ToolRisk.READ,
        audit_log=audit_log,
        span_sink=span_sink,
    )
    async def search_logs(
        account_id: str,
        tenant_id: str,
        user_roles: list[str],
        since: str | None = None,
        level: str | None = None,
        text: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return store.search(
            account_id=account_id,
            tenant_id=tenant_id,
            since=since,
            level=level,
            text=text,
            limit=limit,
        )

    return search_logs


# ---------------------------------------------------------------------------
# MCPServer registration
# ---------------------------------------------------------------------------


def create_logs_server(
    store: LogStore,
    audit_log: AuditLog | None = None,
) -> Any:
    """Return a configured MCPServer for the logs tool."""
    from mcp.server.mcpserver import MCPServer

    server = MCPServer("resolute-logs")
    search_logs_fn = make_search_logs_tool(store, audit_log=audit_log)

    @server.tool()
    async def search_logs(
        account_id: str,
        tenant_id: str,
        user_roles: list[str],
        since: str | None = None,
        level: str | None = None,
        text: str | None = None,
        limit: int = 50,
        token: str = "",
    ) -> list[dict[str, Any]]:
        """Search application event logs for the given account."""
        result: list[dict[str, Any]] = await search_logs_fn(
            token=token,
            account_id=account_id,
            tenant_id=tenant_id,
            user_roles=user_roles,
            since=since,
            level=level,
            text=text,
            limit=limit,
        )
        return result

    return server
