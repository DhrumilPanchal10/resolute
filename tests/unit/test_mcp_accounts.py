"""Offline unit tests for mcp_servers/accounts.py (T4.3).

Uses locally-signed RSA JWTs and in-memory AccountStore — no DB, no network.
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
# RSA key pair for offline JWT signing
# ---------------------------------------------------------------------------

_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PUBLIC_KEY = _PRIVATE_KEY.public_key()
_KID = "accounts-test-kid"


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
    role: str = "support_engineer",
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
# Shared in-memory fixture data
# ---------------------------------------------------------------------------


def _make_store() -> object:
    from resolute.mcp_servers.accounts import AccountStore

    accounts = [
        {
            "id": "acct-001",
            "tenant_id": "tenant_1",
            "name": "Northwind Customer 1",
            "email": "cust1@northwind.example.com",
            "plan": "pro",
            "mrr_usd": 199.0,
            "created_at": "2023-01-01T00:00:00Z",
        },
        {
            "id": "acct-002",
            "tenant_id": "tenant_1",
            "name": "Northwind Customer 2",
            "email": "cust2@northwind.example.com",
            "plan": "enterprise",
            "mrr_usd": 999.0,
            "created_at": "2023-02-01T00:00:00Z",
        },
        {
            "id": "acct-other",
            "tenant_id": "tenant_2",
            "name": "Acme Customer 1",
            "email": "cust1@acme.example.com",
            "plan": "starter",
            "mrr_usd": 49.0,
            "created_at": "2023-03-01T00:00:00Z",
        },
    ]
    invoices = [
        {
            "id": "inv-001",
            "tenant_id": "tenant_1",
            "account_id": "acct-001",
            "amount_usd": 199.0,
            "status": "paid",
            "issued_at": "2023-02-01T00:00:00Z",
        },
        {
            "id": "inv-002",
            "tenant_id": "tenant_1",
            "account_id": "acct-001",
            "amount_usd": 199.0,
            "status": "open",
            "issued_at": "2023-03-01T00:00:00Z",
        },
        {
            "id": "inv-003",
            "tenant_id": "tenant_1",
            "account_id": "acct-002",
            "amount_usd": 999.0,
            "status": "paid",
            "issued_at": "2023-02-01T00:00:00Z",
        },
        {
            "id": "inv-other",
            "tenant_id": "tenant_2",
            "account_id": "acct-other",
            "amount_usd": 49.0,
            "status": "paid",
            "issued_at": "2023-02-01T00:00:00Z",
        },
    ]
    return AccountStore(accounts=accounts, invoices=invoices)


# ---------------------------------------------------------------------------
# get_account tests
# ---------------------------------------------------------------------------


class TestGetAccount:
    @pytest.mark.asyncio
    async def test_returns_account(self) -> None:
        from resolute.mcp_servers.accounts import make_get_account_tool

        store = _make_store()
        tool = make_get_account_tool(store)
        token = _make_token(role="support_engineer")

        result = await tool(
            token=token,
            account_id="acct-001",
            tenant_id="tenant_1",
            user_roles=["support_engineer"],
        )
        assert result is not None
        assert result["id"] == "acct-001"
        assert result["plan"] == "pro"

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_account(self) -> None:
        from resolute.mcp_servers.accounts import make_get_account_tool

        store = _make_store()
        tool = make_get_account_tool(store)
        token = _make_token()

        result = await tool(
            token=token,
            account_id="acct-nonexistent",
            tenant_id="tenant_1",
            user_roles=["support_engineer"],
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_cross_tenant_isolation(self) -> None:
        from resolute.mcp_servers.accounts import make_get_account_tool

        store = _make_store()
        tool = make_get_account_tool(store)
        token = _make_token()

        result = await tool(
            token=token,
            account_id="acct-other",  # belongs to tenant_2
            tenant_id="tenant_1",     # caller is tenant_1
            user_roles=["support_engineer"],
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_audit_events_written(self) -> None:
        from agentcore.audit import AuditLog
        from resolute.mcp_servers.accounts import make_get_account_tool

        log = AuditLog()
        store = _make_store()
        tool = make_get_account_tool(store, audit_log=log)
        token = _make_token()

        await tool(
            token=token,
            account_id="acct-001",
            tenant_id="tenant_1",
            user_roles=["support_engineer"],
        )
        types = [e.event_type for e in log.entries()]
        assert "tool_call_start" in types
        assert "tool_call_success" in types

    @pytest.mark.asyncio
    async def test_missing_token_raises(self) -> None:
        from resolute.mcp_servers.base import ToolPermissionError
        from resolute.mcp_servers.accounts import make_get_account_tool

        store = _make_store()
        tool = make_get_account_tool(store)

        with pytest.raises(ToolPermissionError, match="missing"):
            await tool(
                token="",
                account_id="acct-001",
                tenant_id="tenant_1",
                user_roles=["support_engineer"],
            )

    @pytest.mark.asyncio
    async def test_expired_token_raises(self) -> None:
        from resolute.mcp_servers.base import ToolPermissionError
        from resolute.mcp_servers.accounts import make_get_account_tool

        store = _make_store()
        tool = make_get_account_tool(store)
        token = _make_token(exp_offset=-10)

        with pytest.raises(ToolPermissionError, match="expired"):
            await tool(
                token=token,
                account_id="acct-001",
                tenant_id="tenant_1",
                user_roles=["support_engineer"],
            )


# ---------------------------------------------------------------------------
# get_invoices tests
# ---------------------------------------------------------------------------


class TestGetInvoices:
    @pytest.mark.asyncio
    async def test_returns_invoices_for_account(self) -> None:
        from resolute.mcp_servers.accounts import make_get_invoices_tool

        store = _make_store()
        tool = make_get_invoices_tool(store)
        token = _make_token(role="support_engineer")

        results = await tool(
            token=token,
            account_id="acct-001",
            tenant_id="tenant_1",
            user_roles=["support_engineer"],
        )
        assert len(results) == 2
        ids = {r["id"] for r in results}
        assert ids == {"inv-001", "inv-002"}

    @pytest.mark.asyncio
    async def test_limit_respected(self) -> None:
        from resolute.mcp_servers.accounts import make_get_invoices_tool

        store = _make_store()
        tool = make_get_invoices_tool(store)
        token = _make_token()

        results = await tool(
            token=token,
            account_id="acct-001",
            tenant_id="tenant_1",
            user_roles=["support_engineer"],
            limit=1,
        )
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_cross_tenant_invoices_excluded(self) -> None:
        from resolute.mcp_servers.accounts import make_get_invoices_tool

        store = _make_store()
        tool = make_get_invoices_tool(store)
        token = _make_token()

        results = await tool(
            token=token,
            account_id="acct-other",
            tenant_id="tenant_1",
            user_roles=["support_engineer"],
        )
        assert results == []

    @pytest.mark.asyncio
    async def test_contractor_denied_invoice_read(self) -> None:
        from resolute.mcp_servers.base import ToolPermissionError
        from resolute.mcp_servers.accounts import make_get_invoices_tool

        store = _make_store()
        tool = make_get_invoices_tool(store)
        token = _make_token(role="contractor")

        with pytest.raises(ToolPermissionError):
            await tool(
                token=token,
                account_id="acct-001",
                tenant_id="tenant_1",
                user_roles=["contractor"],
            )

    @pytest.mark.asyncio
    async def test_span_emitted(self) -> None:
        from resolute.mcp_servers.accounts import make_get_invoices_tool

        spans: list = []
        store = _make_store()
        tool = make_get_invoices_tool(store, span_sink=spans)
        token = _make_token()

        await tool(
            token=token,
            account_id="acct-001",
            tenant_id="tenant_1",
            user_roles=["support_engineer"],
        )
        assert len(spans) == 1
        assert spans[0].success is True


# ---------------------------------------------------------------------------
# get_usage tests
# ---------------------------------------------------------------------------


class TestGetUsage:
    @pytest.mark.asyncio
    async def test_returns_usage_stats(self) -> None:
        from resolute.mcp_servers.accounts import make_get_usage_tool

        store = _make_store()
        tool = make_get_usage_tool(store)
        token = _make_token()

        result = await tool(
            token=token,
            account_id="acct-001",
            tenant_id="tenant_1",
            user_roles=["support_engineer"],
        )
        assert result is not None
        assert result["plan"] == "pro"
        assert result["mrr_usd"] == 199.0
        assert result["invoice_count"] == 2
        assert result["total_paid_usd"] == 199.0  # only inv-001 is paid
        assert result["open_invoice_count"] == 1

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_account(self) -> None:
        from resolute.mcp_servers.accounts import make_get_usage_tool

        store = _make_store()
        tool = make_get_usage_tool(store)
        token = _make_token()

        result = await tool(
            token=token,
            account_id="acct-nonexistent",
            tenant_id="tenant_1",
            user_roles=["support_engineer"],
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_cross_tenant_returns_none(self) -> None:
        from resolute.mcp_servers.accounts import make_get_usage_tool

        store = _make_store()
        tool = make_get_usage_tool(store)
        token = _make_token()

        result = await tool(
            token=token,
            account_id="acct-other",
            tenant_id="tenant_1",
            user_roles=["support_engineer"],
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_contractor_can_read_account_usage(self) -> None:
        from resolute.mcp_servers.accounts import make_get_usage_tool

        store = _make_store()
        tool = make_get_usage_tool(store)
        token = _make_token(role="contractor")

        result = await tool(
            token=token,
            account_id="acct-001",
            tenant_id="tenant_1",
            user_roles=["contractor"],
        )
        # account.read is allowed for contractor
        assert result is not None
        assert result["plan"] == "pro"
