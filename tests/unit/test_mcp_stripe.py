"""Offline unit tests for mcp_servers/stripe.py (T4.6).

Covers:
  - Happy path: issue_credit and refund_invoice succeed
  - Approval gating: amounts > threshold require valid approval_token
  - Idempotency: second call with same (ticket_id, action, args) returns cached result
  - RBAC denial: contractor and support_engineer cannot call write tools
  - Audit rows written on success and denial
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

# ---------------------------------------------------------------------------
# RSA key pair
# ---------------------------------------------------------------------------

_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PUBLIC_KEY = _PRIVATE_KEY.public_key()
_KID = "stripe-test-kid"


def _jwks_dict() -> dict[str, Any]:
    import json

    from jwt.algorithms import RSAAlgorithm

    jwk_dict = json.loads(RSAAlgorithm.to_jwk(_PUBLIC_KEY))
    jwk_dict["kid"] = _KID
    return {"keys": [jwk_dict]}


def _make_token(
    *,
    sub: str = "user_1",
    org_id: str = "tenant_1",
    role: str = "lead",
    exp_offset: int = 3600,
) -> str:
    payload: dict[str, Any] = {
        "sub": sub,
        "org_id": org_id,
        "role": role,
        "iat": int(time.time()),
        "exp": int(time.time()) + exp_offset,
    }
    priv_pem = _PRIVATE_KEY.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )
    return jwt.encode(payload, priv_pem, algorithm="RS256", headers={"kid": _KID})


@pytest.fixture(autouse=True)
def inject_jwks():
    from agentcore.auth import _set_test_jwks

    _set_test_jwks(_jwks_dict())
    yield
    _set_test_jwks(None)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _make_store(approved_tokens: set[str] | None = None) -> object:
    from resolute.mcp_servers.stripe import FakeStripeClient, StripeStore

    return StripeStore(
        gateway=FakeStripeClient(),
        approved_tokens=approved_tokens or set(),
        threshold_usd=500.0,
    )


# ---------------------------------------------------------------------------
# issue_credit — happy path
# ---------------------------------------------------------------------------


class TestIssueCredit:
    @pytest.mark.asyncio
    async def test_small_amount_no_approval_needed(self) -> None:
        from resolute.mcp_servers.stripe import make_issue_credit_tool

        store = _make_store()
        tool = make_issue_credit_tool(store)
        token = _make_token(role="lead")

        result = await tool(
            token=token,
            account_id="acct-001",
            amount_usd=100.0,
            ticket_id="ticket-001",
            tenant_id="tenant_1",
            user_roles=["lead"],
        )
        assert result["status"] == "issued"
        assert result["amount_usd"] == 100.0
        assert "idempotency_key" in result

    @pytest.mark.asyncio
    async def test_large_amount_with_valid_approval(self) -> None:
        from resolute.mcp_servers.stripe import make_issue_credit_tool

        store = _make_store(approved_tokens={"tok-approved"})
        tool = make_issue_credit_tool(store)
        token = _make_token(role="admin")

        result = await tool(
            token=token,
            account_id="acct-001",
            amount_usd=750.0,
            ticket_id="ticket-001",
            tenant_id="tenant_1",
            user_roles=["admin"],
            approval_token="tok-approved",
        )
        assert result["status"] == "issued"
        assert result["amount_usd"] == 750.0

    @pytest.mark.asyncio
    async def test_large_amount_no_approval_raises(self) -> None:
        from resolute.mcp_servers.stripe import ApprovalRequiredError, make_issue_credit_tool

        store = _make_store()
        tool = make_issue_credit_tool(store)
        token = _make_token(role="lead")

        with pytest.raises(ApprovalRequiredError):
            await tool(
                token=token,
                account_id="acct-001",
                amount_usd=600.0,
                ticket_id="ticket-001",
                tenant_id="tenant_1",
                user_roles=["lead"],
            )

    @pytest.mark.asyncio
    async def test_large_amount_invalid_approval_raises(self) -> None:
        from resolute.mcp_servers.stripe import ApprovalRequiredError, make_issue_credit_tool

        store = _make_store(approved_tokens={"tok-valid"})
        tool = make_issue_credit_tool(store)
        token = _make_token(role="lead")

        with pytest.raises(ApprovalRequiredError):
            await tool(
                token=token,
                account_id="acct-001",
                amount_usd=600.0,
                ticket_id="ticket-001",
                tenant_id="tenant_1",
                user_roles=["lead"],
                approval_token="tok-wrong",
            )

    @pytest.mark.asyncio
    async def test_idempotency_returns_cached_result(self) -> None:
        from resolute.mcp_servers.stripe import FakeStripeClient, StripeStore, make_issue_credit_tool

        fake = FakeStripeClient()
        store = StripeStore(gateway=fake)
        tool = make_issue_credit_tool(store)
        token = _make_token(role="lead")

        kwargs = dict(
            token=token,
            account_id="acct-001",
            amount_usd=200.0,
            ticket_id="ticket-001",
            tenant_id="tenant_1",
            user_roles=["lead"],
        )

        result1 = await tool(**kwargs)
        result2 = await tool(**kwargs)

        assert result1["idempotency_key"] == result2["idempotency_key"]
        assert result2.get("idempotent") is True
        # Only one real Stripe call made
        assert len(fake.credits_issued) == 1

    @pytest.mark.asyncio
    async def test_different_ticket_id_not_idempotent(self) -> None:
        from resolute.mcp_servers.stripe import FakeStripeClient, StripeStore, make_issue_credit_tool

        fake = FakeStripeClient()
        store = StripeStore(gateway=fake)
        tool = make_issue_credit_tool(store)
        token = _make_token(role="lead")

        await tool(
            token=token,
            account_id="acct-001",
            amount_usd=200.0,
            ticket_id="ticket-001",
            tenant_id="tenant_1",
            user_roles=["lead"],
        )
        await tool(
            token=token,
            account_id="acct-001",
            amount_usd=200.0,
            ticket_id="ticket-002",  # different ticket
            tenant_id="tenant_1",
            user_roles=["lead"],
        )
        assert len(fake.credits_issued) == 2

    @pytest.mark.asyncio
    async def test_audit_events_written(self) -> None:
        from agentcore.audit import AuditLog
        from resolute.mcp_servers.stripe import make_issue_credit_tool

        log = AuditLog()
        store = _make_store()
        tool = make_issue_credit_tool(store, audit_log=log)
        token = _make_token(role="lead")

        await tool(
            token=token,
            account_id="acct-001",
            amount_usd=50.0,
            ticket_id="ticket-001",
            tenant_id="tenant_1",
            user_roles=["lead"],
        )
        types = [e.event_type for e in log.entries()]
        assert "tool_call_start" in types
        assert "tool_call_success" in types

    @pytest.mark.asyncio
    async def test_support_engineer_denied_credit(self) -> None:
        from resolute.mcp_servers.base import ToolPermissionError
        from resolute.mcp_servers.stripe import make_issue_credit_tool

        store = _make_store()
        tool = make_issue_credit_tool(store)
        token = _make_token(role="support_engineer")

        with pytest.raises(ToolPermissionError):
            await tool(
                token=token,
                account_id="acct-001",
                amount_usd=50.0,
                ticket_id="ticket-001",
                tenant_id="tenant_1",
                user_roles=["support_engineer"],
            )

    @pytest.mark.asyncio
    async def test_contractor_denied_credit(self) -> None:
        from resolute.mcp_servers.base import ToolPermissionError
        from resolute.mcp_servers.stripe import make_issue_credit_tool

        store = _make_store()
        tool = make_issue_credit_tool(store)
        token = _make_token(role="contractor")

        with pytest.raises(ToolPermissionError):
            await tool(
                token=token,
                account_id="acct-001",
                amount_usd=50.0,
                ticket_id="ticket-001",
                tenant_id="tenant_1",
                user_roles=["contractor"],
            )


# ---------------------------------------------------------------------------
# refund_invoice — happy path
# ---------------------------------------------------------------------------


class TestRefundInvoice:
    @pytest.mark.asyncio
    async def test_small_refund_no_approval_needed(self) -> None:
        from resolute.mcp_servers.stripe import make_refund_invoice_tool

        store = _make_store()
        tool = make_refund_invoice_tool(store)
        token = _make_token(role="lead")

        result = await tool(
            token=token,
            invoice_id="inv-001",
            amount_usd=299.0,
            ticket_id="ticket-002",
            tenant_id="tenant_1",
            user_roles=["lead"],
        )
        assert result["status"] == "succeeded"
        assert result["invoice_id"] == "inv-001"
        assert "idempotency_key" in result

    @pytest.mark.asyncio
    async def test_large_refund_requires_approval(self) -> None:
        from resolute.mcp_servers.stripe import ApprovalRequiredError, make_refund_invoice_tool

        store = _make_store()
        tool = make_refund_invoice_tool(store)
        token = _make_token(role="admin")

        with pytest.raises(ApprovalRequiredError):
            await tool(
                token=token,
                invoice_id="inv-001",
                amount_usd=999.0,
                ticket_id="ticket-002",
                tenant_id="tenant_1",
                user_roles=["admin"],
            )

    @pytest.mark.asyncio
    async def test_large_refund_with_approval_succeeds(self) -> None:
        from resolute.mcp_servers.stripe import make_refund_invoice_tool

        store = _make_store(approved_tokens={"tok-hr-approved"})
        tool = make_refund_invoice_tool(store)
        token = _make_token(role="admin")

        result = await tool(
            token=token,
            invoice_id="inv-001",
            amount_usd=999.0,
            ticket_id="ticket-002",
            tenant_id="tenant_1",
            user_roles=["admin"],
            approval_token="tok-hr-approved",
        )
        assert result["status"] == "succeeded"

    @pytest.mark.asyncio
    async def test_idempotency_returns_cached_result(self) -> None:
        from resolute.mcp_servers.stripe import FakeStripeClient, StripeStore, make_refund_invoice_tool

        fake = FakeStripeClient()
        store = StripeStore(gateway=fake)
        tool = make_refund_invoice_tool(store)
        token = _make_token(role="lead")

        kwargs = dict(
            token=token,
            invoice_id="inv-001",
            amount_usd=100.0,
            ticket_id="ticket-002",
            tenant_id="tenant_1",
            user_roles=["lead"],
        )
        r1 = await tool(**kwargs)
        r2 = await tool(**kwargs)

        assert r1["idempotency_key"] == r2["idempotency_key"]
        assert r2.get("idempotent") is True
        assert len(fake.refunds_issued) == 1

    @pytest.mark.asyncio
    async def test_support_engineer_denied_refund(self) -> None:
        from resolute.mcp_servers.base import ToolPermissionError
        from resolute.mcp_servers.stripe import make_refund_invoice_tool

        store = _make_store()
        tool = make_refund_invoice_tool(store)
        token = _make_token(role="support_engineer")

        with pytest.raises(ToolPermissionError):
            await tool(
                token=token,
                invoice_id="inv-001",
                amount_usd=50.0,
                ticket_id="ticket-002",
                tenant_id="tenant_1",
                user_roles=["support_engineer"],
            )

    @pytest.mark.asyncio
    async def test_span_emitted_on_success(self) -> None:
        from resolute.mcp_servers.stripe import make_refund_invoice_tool

        spans: list = []
        store = _make_store()
        tool = make_refund_invoice_tool(store, span_sink=spans)
        token = _make_token(role="lead")

        await tool(
            token=token,
            invoice_id="inv-001",
            amount_usd=49.99,
            ticket_id="ticket-002",
            tenant_id="tenant_1",
            user_roles=["lead"],
        )
        assert len(spans) == 1
        assert spans[0].success is True

    @pytest.mark.asyncio
    async def test_audit_row_written_on_success(self) -> None:
        from agentcore.audit import AuditLog
        from resolute.mcp_servers.stripe import make_refund_invoice_tool

        log = AuditLog()
        store = _make_store()
        tool = make_refund_invoice_tool(store, audit_log=log)
        token = _make_token(role="lead")

        await tool(
            token=token,
            invoice_id="inv-001",
            amount_usd=50.0,
            ticket_id="ticket-002",
            tenant_id="tenant_1",
            user_roles=["lead"],
        )
        types = [e.event_type for e in log.entries()]
        assert "tool_call_start" in types
        assert "tool_call_success" in types


# ---------------------------------------------------------------------------
# _idempotency_key unit tests
# ---------------------------------------------------------------------------


class TestIdempotencyKey:
    def test_same_args_same_key(self) -> None:
        from resolute.mcp_servers.stripe import _idempotency_key

        k1 = _idempotency_key("ticket-1", "refund", invoice_id="inv-1", amount_usd=100.0)
        k2 = _idempotency_key("ticket-1", "refund", invoice_id="inv-1", amount_usd=100.0)
        assert k1 == k2

    def test_different_ticket_different_key(self) -> None:
        from resolute.mcp_servers.stripe import _idempotency_key

        k1 = _idempotency_key("ticket-1", "refund", invoice_id="inv-1", amount_usd=100.0)
        k2 = _idempotency_key("ticket-2", "refund", invoice_id="inv-1", amount_usd=100.0)
        assert k1 != k2

    def test_different_action_different_key(self) -> None:
        from resolute.mcp_servers.stripe import _idempotency_key

        k1 = _idempotency_key("ticket-1", "refund", amount_usd=100.0)
        k2 = _idempotency_key("ticket-1", "credit", amount_usd=100.0)
        assert k1 != k2

    def test_key_length_32(self) -> None:
        from resolute.mcp_servers.stripe import _idempotency_key

        k = _idempotency_key("ticket-1", "refund", amount_usd=100.0)
        assert len(k) == 32
