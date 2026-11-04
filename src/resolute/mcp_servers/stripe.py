"""Stripe MCP server — issue_credit, refund_invoice in TEST mode.

Architecture
------------
StripeGateway is an injectable protocol satisfied by both StripeClient
(real httpx-based Stripe REST v1 calls) and FakeStripeClient (in-memory
for unit tests).

StripeStore wraps the gateway with:
  - Approval gating: amounts above APPROVAL_THRESHOLD_USD require a valid
    approval_token (checked against injected approved_tokens set, or the
    `approvals` table in production).
  - Idempotency: key = sha256(ticket_id + action + sorted args); if the key
    was seen before, the cached result is returned immediately.

Two MCP tools:

  issue_credit(account_id, amount_usd, ticket_id, approval_token)
      Credit a customer account balance.  Requires invoice.credit (lead/admin).

  refund_invoice(invoice_id, amount_usd, ticket_id, approval_token)
      Refund a Stripe invoice.  Requires invoice.refund (lead/admin).

Both are ToolRisk.WRITE.  Large amounts (> APPROVAL_THRESHOLD_USD) raise
ApprovalRequiredError unless a valid approval_token is supplied.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from agentcore.audit import AuditLog
from agentcore.errors import ResoluteError
from resolute.mcp_servers.base import ToolRisk, mcp_tool

# ---------------------------------------------------------------------------
# Policy constants
# ---------------------------------------------------------------------------

APPROVAL_THRESHOLD_USD: float = 500.0


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ApprovalRequiredError(ResoluteError):
    """Raised when a financial operation exceeds the approval threshold."""

    def __init__(self, amount: float, threshold: float) -> None:
        super().__init__(
            f"Amount ${amount:.2f} exceeds policy threshold ${threshold:.2f}; "
            "an approved approval_token is required"
        )
        self.amount = amount
        self.threshold = threshold


# ---------------------------------------------------------------------------
# Idempotency key
# ---------------------------------------------------------------------------


def _idempotency_key(ticket_id: str, action: str, **kwargs: Any) -> str:
    """SHA-256 of (ticket_id, action, sorted-args JSON) → 32-char hex."""
    payload = json.dumps({"ticket_id": ticket_id, "action": action, **kwargs}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


# ---------------------------------------------------------------------------
# Gateway Protocol
# ---------------------------------------------------------------------------


class StripeGateway(Protocol):
    """Duck-type interface for Stripe operations."""

    async def issue_credit(
        self,
        account_id: str,
        amount_usd: float,
        idempotency_key: str,
    ) -> dict[str, Any]: ...

    async def refund_invoice(
        self,
        invoice_id: str,
        amount_usd: float,
        idempotency_key: str,
    ) -> dict[str, Any]: ...


# ---------------------------------------------------------------------------
# Real Stripe REST client (TEST mode only)
# ---------------------------------------------------------------------------


@dataclass
class StripeClient:
    """Thin async wrapper around the Stripe REST API v1.

    Args:
        api_key:  Stripe TEST secret key (sk_test_...).
        base_url: Override for custom test servers.
    """

    api_key: str
    base_url: str = "https://api.stripe.com"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    async def issue_credit(
        self,
        account_id: str,
        amount_usd: float,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Apply a negative balance transaction (credit) to the customer."""
        import httpx

        # Stripe amounts are in cents, negative = credit
        amount_cents = -int(round(amount_usd * 100))
        async with httpx.AsyncClient(headers=self._headers(), timeout=10) as client:
            resp = await client.post(
                f"{self.base_url}/v1/customers/{account_id}/balance_transactions",
                data={
                    "amount": str(amount_cents),
                    "currency": "usd",
                    "description": f"Support credit — idempotency {idempotency_key}",
                },
                headers={"Idempotency-Key": idempotency_key},
            )
            resp.raise_for_status()
            raw = resp.json()
        return {
            "credit_id": raw.get("id", ""),
            "account_id": account_id,
            "amount_usd": amount_usd,
            "status": "issued",
            "created": raw.get("created", ""),
        }

    async def refund_invoice(
        self,
        invoice_id: str,
        amount_usd: float,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Create a Stripe refund for the given invoice's payment intent."""
        import httpx

        amount_cents = int(round(amount_usd * 100))
        async with httpx.AsyncClient(headers=self._headers(), timeout=10) as client:
            # Look up the invoice to get the payment_intent
            inv_resp = await client.get(f"{self.base_url}/v1/invoices/{invoice_id}")
            inv_resp.raise_for_status()
            payment_intent = inv_resp.json().get("payment_intent", "")

            resp = await client.post(
                f"{self.base_url}/v1/refunds",
                data={
                    "payment_intent": payment_intent,
                    "amount": str(amount_cents),
                },
                headers={"Idempotency-Key": idempotency_key},
            )
            resp.raise_for_status()
            raw = resp.json()
        return {
            "refund_id": raw.get("id", ""),
            "invoice_id": invoice_id,
            "amount_usd": amount_usd,
            "status": raw.get("status", "succeeded"),
            "created": raw.get("created", ""),
        }


# ---------------------------------------------------------------------------
# In-memory fake for unit tests
# ---------------------------------------------------------------------------


@dataclass
class FakeStripeClient:
    """In-memory Stripe gateway for offline unit tests."""

    credits_issued: list[dict[str, Any]] = field(default_factory=list)
    refunds_issued: list[dict[str, Any]] = field(default_factory=list)

    async def issue_credit(
        self,
        account_id: str,
        amount_usd: float,
        idempotency_key: str,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "credit_id": f"cr_{idempotency_key[:8]}",
            "account_id": account_id,
            "amount_usd": amount_usd,
            "status": "issued",
            "created": datetime.now(UTC).isoformat(),
        }
        self.credits_issued.append(result)
        return result

    async def refund_invoice(
        self,
        invoice_id: str,
        amount_usd: float,
        idempotency_key: str,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "refund_id": f"re_{idempotency_key[:8]}",
            "invoice_id": invoice_id,
            "amount_usd": amount_usd,
            "status": "succeeded",
            "created": datetime.now(UTC).isoformat(),
        }
        self.refunds_issued.append(result)
        return result


# ---------------------------------------------------------------------------
# StripeStore — approval gating + idempotency cache
# ---------------------------------------------------------------------------


@dataclass
class StripeStore:
    """Wraps a StripeGateway with approval checking and idempotency.

    Args:
        gateway:         StripeClient or FakeStripeClient.
        approved_tokens: Set of pre-approved approval tokens (injected in
                         tests; in production queried from the approvals table).
        threshold_usd:   Amounts above this require an approval_token.
    """

    gateway: StripeGateway
    approved_tokens: set[str] = field(default_factory=set)
    idempotency_cache: dict[str, dict[str, Any]] = field(default_factory=dict)
    threshold_usd: float = APPROVAL_THRESHOLD_USD

    def _require_approval(
        self, amount: float, approval_token: str, ticket_id: str, action: str
    ) -> None:
        if amount <= self.threshold_usd:
            return
        if not approval_token or approval_token not in self.approved_tokens:
            raise ApprovalRequiredError(amount, self.threshold_usd)

    async def issue_credit(
        self,
        account_id: str,
        amount_usd: float,
        ticket_id: str,
        approval_token: str = "",
    ) -> dict[str, Any]:
        self._require_approval(amount_usd, approval_token, ticket_id, "issue_credit")
        key = _idempotency_key(
            ticket_id, "issue_credit", account_id=account_id, amount_usd=amount_usd
        )
        if key in self.idempotency_cache:
            cached = dict(self.idempotency_cache[key])
            cached["idempotent"] = True
            return cached
        result = await self.gateway.issue_credit(account_id, amount_usd, key)
        result["idempotency_key"] = key
        self.idempotency_cache[key] = result
        return result

    async def refund_invoice(
        self,
        invoice_id: str,
        amount_usd: float,
        ticket_id: str,
        approval_token: str = "",
    ) -> dict[str, Any]:
        self._require_approval(amount_usd, approval_token, ticket_id, "refund_invoice")
        key = _idempotency_key(
            ticket_id, "refund_invoice", invoice_id=invoice_id, amount_usd=amount_usd
        )
        if key in self.idempotency_cache:
            cached = dict(self.idempotency_cache[key])
            cached["idempotent"] = True
            return cached
        result = await self.gateway.refund_invoice(invoice_id, amount_usd, key)
        result["idempotency_key"] = key
        self.idempotency_cache[key] = result
        return result


# ---------------------------------------------------------------------------
# Tool factories
# ---------------------------------------------------------------------------


def make_issue_credit_tool(
    store: StripeStore,
    audit_log: AuditLog | None = None,
    span_sink: list[Any] | None = None,
) -> Any:
    """Return a guarded issue_credit coroutine."""

    @mcp_tool(
        "invoice",
        "credit",
        risk=ToolRisk.WRITE,
        audit_log=audit_log,
        span_sink=span_sink,
    )
    async def issue_credit(
        account_id: str,
        amount_usd: float,
        ticket_id: str,
        tenant_id: str,
        user_roles: list[str],
        approval_token: str = "",
    ) -> dict[str, Any]:
        return await store.issue_credit(
            account_id=account_id,
            amount_usd=amount_usd,
            ticket_id=ticket_id,
            approval_token=approval_token,
        )

    return issue_credit


def make_refund_invoice_tool(
    store: StripeStore,
    audit_log: AuditLog | None = None,
    span_sink: list[Any] | None = None,
) -> Any:
    """Return a guarded refund_invoice coroutine."""

    @mcp_tool(
        "invoice",
        "refund",
        risk=ToolRisk.WRITE,
        audit_log=audit_log,
        span_sink=span_sink,
    )
    async def refund_invoice(
        invoice_id: str,
        amount_usd: float,
        ticket_id: str,
        tenant_id: str,
        user_roles: list[str],
        approval_token: str = "",
    ) -> dict[str, Any]:
        return await store.refund_invoice(
            invoice_id=invoice_id,
            amount_usd=amount_usd,
            ticket_id=ticket_id,
            approval_token=approval_token,
        )

    return refund_invoice


# ---------------------------------------------------------------------------
# MCPServer registration
# ---------------------------------------------------------------------------


def create_stripe_server(
    store: StripeStore,
    audit_log: AuditLog | None = None,
) -> Any:
    """Return a configured MCPServer for both Stripe tools."""
    from mcp.server.mcpserver import MCPServer

    server = MCPServer("resolute-stripe")
    issue_credit_fn = make_issue_credit_tool(store, audit_log=audit_log)
    refund_invoice_fn = make_refund_invoice_tool(store, audit_log=audit_log)

    @server.tool()
    async def issue_credit(
        account_id: str,
        amount_usd: float,
        ticket_id: str,
        tenant_id: str,
        user_roles: list[str],
        approval_token: str = "",
        token: str = "",
    ) -> dict[str, Any]:
        """Issue a credit to a customer account (TEST mode)."""
        result: dict[str, Any] = await issue_credit_fn(
            token=token,
            account_id=account_id,
            amount_usd=amount_usd,
            ticket_id=ticket_id,
            tenant_id=tenant_id,
            user_roles=user_roles,
            approval_token=approval_token,
        )
        return result

    @server.tool()
    async def refund_invoice(
        invoice_id: str,
        amount_usd: float,
        ticket_id: str,
        tenant_id: str,
        user_roles: list[str],
        approval_token: str = "",
        token: str = "",
    ) -> dict[str, Any]:
        """Refund a Stripe invoice (TEST mode)."""
        result: dict[str, Any] = await refund_invoice_fn(
            token=token,
            invoice_id=invoice_id,
            amount_usd=amount_usd,
            ticket_id=ticket_id,
            tenant_id=tenant_id,
            user_roles=user_roles,
            approval_token=approval_token,
        )
        return result

    return server
