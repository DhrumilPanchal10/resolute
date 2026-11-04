"""Offline unit tests for mcp_servers/logs.py (T4.5).

Uses locally-signed RSA JWTs and in-memory LogStore — no DB, no network.
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
_KID = "logs-test-kid"


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
    from resolute.mcp_servers.logs import LogStore

    return LogStore(
        entries=[
            {
                "id": "log-001",
                "tenant_id": "tenant_1",
                "account_id": "acct-001",
                "level": "INFO",
                "message": "Account created on pro plan",
                "occurred_at": "2024-01-01T10:00:00Z",
            },
            {
                "id": "log-002",
                "tenant_id": "tenant_1",
                "account_id": "acct-001",
                "level": "WARN",
                "message": "Payment retry attempted for invoice renewal",
                "occurred_at": "2024-01-02T10:00:00Z",
            },
            {
                "id": "log-003",
                "tenant_id": "tenant_1",
                "account_id": "acct-001",
                "level": "ERROR",
                "message": "Invoice generation failed due to billing error",
                "occurred_at": "2024-01-03T10:00:00Z",
            },
            {
                "id": "log-004",
                "tenant_id": "tenant_1",
                "account_id": "acct-001",
                "level": "INFO",
                "message": "Support ticket opened by user",
                "occurred_at": "2024-01-04T10:00:00Z",
            },
            {
                "id": "log-005",
                "tenant_id": "tenant_1",
                "account_id": "acct-002",
                "level": "ERROR",
                "message": "Authentication error for account acct-002",
                "occurred_at": "2024-01-01T12:00:00Z",
            },
            {
                "id": "log-006",
                "tenant_id": "tenant_2",
                "account_id": "acct-001",
                "level": "ERROR",
                "message": "Cross-tenant log entry that must never leak",
                "occurred_at": "2024-01-01T12:00:00Z",
            },
        ]
    )


# ---------------------------------------------------------------------------
# Happy path tests
# ---------------------------------------------------------------------------


class TestSearchLogs:
    @pytest.mark.asyncio
    async def test_returns_logs_for_account(self) -> None:
        from resolute.mcp_servers.logs import make_search_logs_tool

        store = _make_store()
        tool = make_search_logs_tool(store)
        token = _make_token()

        results = await tool(
            token=token,
            account_id="acct-001",
            tenant_id="tenant_1",
            user_roles=["support_engineer"],
        )
        assert len(results) == 4
        ids = {r["id"] for r in results}
        assert "log-001" in ids
        assert "log-006" not in ids  # cross-tenant excluded

    @pytest.mark.asyncio
    async def test_level_filter(self) -> None:
        from resolute.mcp_servers.logs import make_search_logs_tool

        store = _make_store()
        tool = make_search_logs_tool(store)
        token = _make_token()

        results = await tool(
            token=token,
            account_id="acct-001",
            tenant_id="tenant_1",
            user_roles=["support_engineer"],
            level="ERROR",
        )
        assert len(results) == 1
        assert results[0]["id"] == "log-003"
        assert all(r["level"] == "ERROR" for r in results)

    @pytest.mark.asyncio
    async def test_level_filter_case_insensitive(self) -> None:
        from resolute.mcp_servers.logs import make_search_logs_tool

        store = _make_store()
        tool = make_search_logs_tool(store)
        token = _make_token()

        results = await tool(
            token=token,
            account_id="acct-001",
            tenant_id="tenant_1",
            user_roles=["support_engineer"],
            level="warn",
        )
        assert len(results) == 1
        assert results[0]["level"] == "WARN"

    @pytest.mark.asyncio
    async def test_since_filter_excludes_old_entries(self) -> None:
        from resolute.mcp_servers.logs import make_search_logs_tool

        store = _make_store()
        tool = make_search_logs_tool(store)
        token = _make_token()

        results = await tool(
            token=token,
            account_id="acct-001",
            tenant_id="tenant_1",
            user_roles=["support_engineer"],
            since="2024-01-03T00:00:00Z",
        )
        # Only log-003 and log-004 are on/after 2024-01-03
        assert len(results) == 2
        ids = {r["id"] for r in results}
        assert "log-001" not in ids
        assert "log-002" not in ids

    @pytest.mark.asyncio
    async def test_text_filter(self) -> None:
        from resolute.mcp_servers.logs import make_search_logs_tool

        store = _make_store()
        tool = make_search_logs_tool(store)
        token = _make_token()

        results = await tool(
            token=token,
            account_id="acct-001",
            tenant_id="tenant_1",
            user_roles=["support_engineer"],
            text="invoice",
        )
        # log-002 (invoice renewal) and log-003 (invoice generation)
        assert len(results) == 2
        assert all("invoice" in r["message"].lower() for r in results)

    @pytest.mark.asyncio
    async def test_limit_respected(self) -> None:
        from resolute.mcp_servers.logs import make_search_logs_tool

        store = _make_store()
        tool = make_search_logs_tool(store)
        token = _make_token()

        results = await tool(
            token=token,
            account_id="acct-001",
            tenant_id="tenant_1",
            user_roles=["support_engineer"],
            limit=2,
        )
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_cross_tenant_entries_excluded(self) -> None:
        from resolute.mcp_servers.logs import make_search_logs_tool

        store = _make_store()
        tool = make_search_logs_tool(store)
        token = _make_token()

        results = await tool(
            token=token,
            account_id="acct-001",
            tenant_id="tenant_1",
            user_roles=["support_engineer"],
        )
        assert not any(r["tenant_id"] == "tenant_2" for r in results)

    @pytest.mark.asyncio
    async def test_different_account_excluded(self) -> None:
        from resolute.mcp_servers.logs import make_search_logs_tool

        store = _make_store()
        tool = make_search_logs_tool(store)
        token = _make_token()

        results = await tool(
            token=token,
            account_id="acct-002",
            tenant_id="tenant_1",
            user_roles=["support_engineer"],
        )
        assert all(r["account_id"] == "acct-002" for r in results)
        assert not any(r["id"] == "log-001" for r in results)

    @pytest.mark.asyncio
    async def test_result_has_expected_keys(self) -> None:
        from resolute.mcp_servers.logs import make_search_logs_tool

        store = _make_store()
        tool = make_search_logs_tool(store)
        token = _make_token()

        results = await tool(
            token=token,
            account_id="acct-001",
            tenant_id="tenant_1",
            user_roles=["support_engineer"],
            limit=1,
        )
        assert len(results) == 1
        assert {"id", "level", "message", "occurred_at"} <= results[0].keys()

    @pytest.mark.asyncio
    async def test_audit_events_written(self) -> None:
        from agentcore.audit import AuditLog
        from resolute.mcp_servers.logs import make_search_logs_tool

        log = AuditLog()
        store = _make_store()
        tool = make_search_logs_tool(store, audit_log=log)
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
    async def test_span_emitted(self) -> None:
        from resolute.mcp_servers.logs import make_search_logs_tool

        spans: list = []
        store = _make_store()
        tool = make_search_logs_tool(store, span_sink=spans)
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
# RBAC tests
# ---------------------------------------------------------------------------


class TestLogsRBAC:
    @pytest.mark.asyncio
    async def test_contractor_denied(self) -> None:
        from resolute.mcp_servers.base import ToolPermissionError
        from resolute.mcp_servers.logs import make_search_logs_tool

        store = _make_store()
        tool = make_search_logs_tool(store)
        token = _make_token(role="contractor")

        with pytest.raises(ToolPermissionError):
            await tool(
                token=token,
                account_id="acct-001",
                tenant_id="tenant_1",
                user_roles=["contractor"],
            )

    @pytest.mark.asyncio
    async def test_missing_token_raises(self) -> None:
        from resolute.mcp_servers.base import ToolPermissionError
        from resolute.mcp_servers.logs import make_search_logs_tool

        store = _make_store()
        tool = make_search_logs_tool(store)

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
        from resolute.mcp_servers.logs import make_search_logs_tool

        store = _make_store()
        tool = make_search_logs_tool(store)
        token = _make_token(exp_offset=-10)

        with pytest.raises(ToolPermissionError, match="expired"):
            await tool(
                token=token,
                account_id="acct-001",
                tenant_id="tenant_1",
                user_roles=["support_engineer"],
            )
