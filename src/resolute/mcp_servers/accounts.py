"""Accounts MCP server — get_account, get_invoices, get_usage.

Architecture
------------
AccountStore is an injectable data layer.  In production it wraps async DB
queries inside `db_session(tenant_id)`.  In unit tests a plain in-memory list
is passed so no Postgres is needed.

Three MCP tools are exposed, all guarded by the standard JWT → RBAC → circuit
→ audit → timeout → span pipeline:

  get_account(account_id, tenant_id, user_roles)
      Returns account metadata or None.  Requires account.read.

  get_invoices(account_id, tenant_id, user_roles, limit=20)
      Returns list of invoices for the account.  Requires invoice.read.

  get_usage(account_id, tenant_id, user_roles)
      Returns derived usage stats (plan, mrr_usd, invoice counts).
      Requires account.read.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from agentcore.audit import AuditLog
from resolute.mcp_servers.base import ToolRisk, mcp_tool

# ---------------------------------------------------------------------------
# AccountStore — injectable data layer
# ---------------------------------------------------------------------------


@dataclass
class AccountStore:
    """In-memory account/invoice store used in unit tests.

    In production, replace with a DB-backed implementation that queries
    via db_session(tenant_id).
    """

    accounts: list[dict[str, Any]] = field(default_factory=list)
    invoices: list[dict[str, Any]] = field(default_factory=list)

    def get_account(self, account_id: str, tenant_id: str) -> dict[str, Any] | None:
        for acct in self.accounts:
            if acct["id"] == account_id and acct["tenant_id"] == tenant_id:
                return acct
        return None

    def get_invoices_for_account(
        self, account_id: str, tenant_id: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        result = [
            inv
            for inv in self.invoices
            if inv["account_id"] == account_id and inv["tenant_id"] == tenant_id
        ]
        return result[:limit]

    def get_usage_stats(self, account_id: str, tenant_id: str) -> dict[str, Any] | None:
        acct = self.get_account(account_id, tenant_id)
        if acct is None:
            return None
        invs = self.get_invoices_for_account(account_id, tenant_id)
        paid_total = sum(
            float(inv.get("amount_usd", 0)) for inv in invs if inv.get("status") == "paid"
        )
        return {
            "account_id": account_id,
            "plan": acct.get("plan", ""),
            "mrr_usd": float(acct.get("mrr_usd", 0)),
            "invoice_count": len(invs),
            "total_paid_usd": round(paid_total, 2),
            "open_invoice_count": sum(1 for inv in invs if inv.get("status") == "open"),
        }


# ---------------------------------------------------------------------------
# Tool factories
# ---------------------------------------------------------------------------


def make_get_account_tool(
    store: AccountStore,
    audit_log: AuditLog | None = None,
    span_sink: list[Any] | None = None,
) -> Callable[..., Any]:
    """Return a guarded get_account coroutine bound to the given AccountStore."""

    @mcp_tool(
        "account",
        "read",
        risk=ToolRisk.READ,
        audit_log=audit_log,
        span_sink=span_sink,
    )
    async def get_account(
        account_id: str,
        tenant_id: str,
        user_roles: list[str],
    ) -> dict[str, Any] | None:
        return store.get_account(account_id, tenant_id)

    return get_account  # type: ignore[no-any-return]


def make_get_invoices_tool(
    store: AccountStore,
    audit_log: AuditLog | None = None,
    span_sink: list[Any] | None = None,
) -> Callable[..., Any]:
    """Return a guarded get_invoices coroutine bound to the given AccountStore."""

    @mcp_tool(
        "invoice",
        "read",
        risk=ToolRisk.READ,
        audit_log=audit_log,
        span_sink=span_sink,
    )
    async def get_invoices(
        account_id: str,
        tenant_id: str,
        user_roles: list[str],
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        return store.get_invoices_for_account(account_id, tenant_id, limit)

    return get_invoices  # type: ignore[no-any-return]


def make_get_usage_tool(
    store: AccountStore,
    audit_log: AuditLog | None = None,
    span_sink: list[Any] | None = None,
) -> Callable[..., Any]:
    """Return a guarded get_usage coroutine bound to the given AccountStore."""

    @mcp_tool(
        "account",
        "read",
        risk=ToolRisk.READ,
        audit_log=audit_log,
        span_sink=span_sink,
    )
    async def get_usage(
        account_id: str,
        tenant_id: str,
        user_roles: list[str],
    ) -> dict[str, Any] | None:
        return store.get_usage_stats(account_id, tenant_id)

    return get_usage  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# MCPServer registration
# ---------------------------------------------------------------------------


def create_accounts_server(
    store: AccountStore,
    audit_log: AuditLog | None = None,
) -> Any:
    """Return a configured MCPServer for all three account tools."""
    from mcp.server.mcpserver import MCPServer

    server = MCPServer("resolute-accounts")
    get_account_fn = make_get_account_tool(store, audit_log=audit_log)
    get_invoices_fn = make_get_invoices_tool(store, audit_log=audit_log)
    get_usage_fn = make_get_usage_tool(store, audit_log=audit_log)

    @server.tool()
    async def get_account(
        account_id: str,
        tenant_id: str,
        user_roles: list[str],
        token: str = "",
    ) -> dict[str, Any] | None:
        """Return account metadata for the given account_id."""
        result: dict[str, Any] | None = await get_account_fn(
            token=token,
            account_id=account_id,
            tenant_id=tenant_id,
            user_roles=user_roles,
        )
        return result

    @server.tool()
    async def get_invoices(
        account_id: str,
        tenant_id: str,
        user_roles: list[str],
        limit: int = 20,
        token: str = "",
    ) -> list[dict[str, Any]]:
        """Return invoices for the given account_id."""
        result: list[dict[str, Any]] = await get_invoices_fn(
            token=token,
            account_id=account_id,
            tenant_id=tenant_id,
            user_roles=user_roles,
            limit=limit,
        )
        return result

    @server.tool()
    async def get_usage(
        account_id: str,
        tenant_id: str,
        user_roles: list[str],
        token: str = "",
    ) -> dict[str, Any] | None:
        """Return derived usage statistics for the given account_id."""
        result: dict[str, Any] | None = await get_usage_fn(
            token=token,
            account_id=account_id,
            tenant_id=tenant_id,
            user_roles=user_roles,
        )
        return result

    return server
