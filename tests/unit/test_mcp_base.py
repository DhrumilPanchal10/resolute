"""Offline unit tests for mcp_servers/base.py (T4.1).

Uses locally-signed RSA JWTs — no network, no MCP server process.
"""

from __future__ import annotations

import asyncio
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
# RSA key pair (shared across all tests)
# ---------------------------------------------------------------------------

_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PUBLIC_KEY = _PRIVATE_KEY.public_key()
_KID = "mcp-test-kid"


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


# ---------------------------------------------------------------------------
# Inject JWKS before every test
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def inject_jwks():
    from agentcore.auth import _set_test_jwks

    _set_test_jwks(_jwks_dict())
    yield
    _set_test_jwks(None)


# ---------------------------------------------------------------------------
# Minimal async tool functions for testing
# ---------------------------------------------------------------------------


async def _read_tool(account_id: str = "a1") -> dict:
    return {"account_id": account_id, "balance": 42}


async def _write_tool(account_id: str = "a1", amount: float = 10.0) -> dict:
    return {"updated": True}


async def _slow_tool(delay: float = 5.0) -> dict:
    await asyncio.sleep(delay)
    return {"done": True}


async def _failing_tool() -> dict:
    raise RuntimeError("tool exploded")


# ---------------------------------------------------------------------------
# call_guarded — happy path
# ---------------------------------------------------------------------------


class TestCallGuarded:
    @pytest.mark.asyncio
    async def test_valid_token_read_succeeds(self) -> None:
        from agentcore.audit import AuditLog
        from resolute.mcp_servers.base import ToolRisk, call_guarded

        log = AuditLog()
        token = _make_token(role="support_engineer")
        result = await call_guarded(
            token=token,
            resource="account",
            action="read",
            risk=ToolRisk.READ,
            tool_name="get_account",
            fn=_read_tool,
            audit_log=log,
            account_id="acct_42",
        )
        assert result["account_id"] == "acct_42"

    @pytest.mark.asyncio
    async def test_audit_events_written(self) -> None:
        from agentcore.audit import AuditLog
        from resolute.mcp_servers.base import ToolRisk, call_guarded

        log = AuditLog()
        token = _make_token()
        await call_guarded(
            token=token,
            resource="account",
            action="read",
            risk=ToolRisk.READ,
            tool_name="get_account",
            fn=_read_tool,
            audit_log=log,
        )
        types = [e.event_type for e in log.entries()]
        assert "tool_call_start" in types
        assert "tool_call_success" in types

    @pytest.mark.asyncio
    async def test_span_emitted(self) -> None:
        from resolute.mcp_servers.base import ToolRisk, call_guarded

        spans: list = []
        token = _make_token()
        await call_guarded(
            token=token,
            resource="account",
            action="read",
            risk=ToolRisk.READ,
            tool_name="get_account",
            fn=_read_tool,
            span_sink=spans,
        )
        assert len(spans) == 1
        assert spans[0].tool_name == "get_account"
        assert spans[0].success is True
        assert spans[0].duration_ms > 0

    @pytest.mark.asyncio
    async def test_lead_can_do_write(self) -> None:
        from resolute.mcp_servers.base import ToolRisk, call_guarded

        token = _make_token(role="lead")
        result = await call_guarded(
            token=token,
            resource="invoice",
            action="refund",
            risk=ToolRisk.WRITE,
            tool_name="refund_invoice",
            fn=_write_tool,
        )
        assert result["updated"] is True


# ---------------------------------------------------------------------------
# call_guarded — permission denials
# ---------------------------------------------------------------------------


class TestCallGuardedDenials:
    @pytest.mark.asyncio
    async def test_missing_token_raises(self) -> None:
        from resolute.mcp_servers.base import ToolPermissionError, ToolRisk, call_guarded

        with pytest.raises(ToolPermissionError, match="missing"):
            await call_guarded(
                token="",
                resource="account",
                action="read",
                risk=ToolRisk.READ,
                tool_name="get_account",
                fn=_read_tool,
            )

    @pytest.mark.asyncio
    async def test_expired_token_raises(self) -> None:
        from resolute.mcp_servers.base import ToolPermissionError, ToolRisk, call_guarded

        token = _make_token(exp_offset=-10)
        with pytest.raises(ToolPermissionError, match="expired"):
            await call_guarded(
                token=token,
                resource="account",
                action="read",
                risk=ToolRisk.READ,
                tool_name="get_account",
                fn=_read_tool,
            )

    @pytest.mark.asyncio
    async def test_wrong_role_raises(self) -> None:
        from resolute.mcp_servers.base import ToolPermissionError, ToolRisk, call_guarded

        # support_engineer cannot approve
        token = _make_token(role="support_engineer")
        with pytest.raises(ToolPermissionError, match="support_engineer"):
            await call_guarded(
                token=token,
                resource="approval",
                action="approve",
                risk=ToolRisk.WRITE,
                tool_name="approve_action",
                fn=_write_tool,
            )

    @pytest.mark.asyncio
    async def test_contractor_cannot_refund(self) -> None:
        from resolute.mcp_servers.base import ToolPermissionError, ToolRisk, call_guarded

        token = _make_token(role="contractor")
        with pytest.raises(ToolPermissionError):
            await call_guarded(
                token=token,
                resource="invoice",
                action="refund",
                risk=ToolRisk.WRITE,
                tool_name="refund_invoice",
                fn=_write_tool,
            )

    @pytest.mark.asyncio
    async def test_error_span_emitted_on_permission_failure(self) -> None:
        """Permission errors must NOT emit a span (gate fires before fn runs)."""
        from resolute.mcp_servers.base import ToolPermissionError, ToolRisk, call_guarded

        spans: list = []
        with pytest.raises(ToolPermissionError):
            await call_guarded(
                token="",
                resource="account",
                action="read",
                risk=ToolRisk.READ,
                tool_name="get_account",
                fn=_read_tool,
                span_sink=spans,
            )
        # Span must NOT be written — permission check fired before the tool ran
        assert len(spans) == 0


# ---------------------------------------------------------------------------
# Timeout
# ---------------------------------------------------------------------------


class TestTimeout:
    @pytest.mark.asyncio
    async def test_slow_tool_times_out(self) -> None:
        from resolute.mcp_servers.base import ToolRisk, call_guarded

        token = _make_token()
        with pytest.raises(asyncio.TimeoutError):
            await call_guarded(
                token=token,
                resource="account",
                action="read",
                risk=ToolRisk.READ,
                tool_name="slow_tool",
                fn=_slow_tool,
                timeout_s=0.05,
                delay=5.0,
            )

    @pytest.mark.asyncio
    async def test_timeout_records_failure_in_circuit(self) -> None:
        from resolute.mcp_servers.base import CircuitBreaker, ToolRisk, call_guarded

        circuit = CircuitBreaker("slow_tool", fail_threshold=1)
        token = _make_token()
        with pytest.raises(asyncio.TimeoutError):
            await call_guarded(
                token=token,
                resource="account",
                action="read",
                risk=ToolRisk.READ,
                tool_name="slow_tool",
                fn=_slow_tool,
                circuit=circuit,
                timeout_s=0.05,
                delay=5.0,
            )
        from resolute.mcp_servers.base import CircuitState

        assert circuit.state == CircuitState.OPEN


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------


class TestCircuitBreaker:
    def test_starts_closed(self) -> None:
        from resolute.mcp_servers.base import CircuitBreaker, CircuitState

        cb = CircuitBreaker("tool", fail_threshold=3)
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request() is True

    def test_opens_after_threshold(self) -> None:
        from resolute.mcp_servers.base import CircuitBreaker, CircuitState

        cb = CircuitBreaker("tool", fail_threshold=3)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.allow_request() is False

    def test_success_resets_counter(self) -> None:
        from resolute.mcp_servers.base import CircuitBreaker, CircuitState

        cb = CircuitBreaker("tool", fail_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        cb.record_failure()
        # Only 1 failure since reset — still closed
        assert cb.state == CircuitState.CLOSED

    def test_transitions_to_half_open_after_timeout(self) -> None:
        from resolute.mcp_servers.base import CircuitBreaker, CircuitState

        cb = CircuitBreaker("tool", fail_threshold=1, reset_timeout_s=0.0)
        cb.record_failure()
        # reset_timeout_s=0 means it transitions immediately
        assert cb.state == CircuitState.HALF_OPEN
        assert cb.allow_request() is True

    def test_half_open_success_closes_circuit(self) -> None:
        from resolute.mcp_servers.base import CircuitBreaker, CircuitState

        cb = CircuitBreaker("tool", fail_threshold=1, reset_timeout_s=0.0)
        cb.record_failure()
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_half_open_failure_reopens(self) -> None:
        from resolute.mcp_servers.base import CircuitBreaker, CircuitState

        # Use a long timeout so the circuit stays OPEN after record_failure
        cb = CircuitBreaker("tool", fail_threshold=1, reset_timeout_s=999.0)
        cb.record_failure()
        assert cb._state == CircuitState.OPEN  # internal OPEN (timeout not elapsed)
        # Simulate time passage by forcing HALF_OPEN
        cb._state = CircuitState.HALF_OPEN
        # A failure during HALF_OPEN should re-open
        cb.record_failure()
        assert cb._state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_open_circuit_raises(self) -> None:
        from resolute.mcp_servers.base import (
            CircuitBreaker,
            CircuitOpenError,
            ToolRisk,
            call_guarded,
        )

        cb = CircuitBreaker("tool", fail_threshold=1)
        cb.record_failure()  # opens the circuit

        token = _make_token()
        with pytest.raises(CircuitOpenError, match="tool"):
            await call_guarded(
                token=token,
                resource="account",
                action="read",
                risk=ToolRisk.READ,
                tool_name="tool",
                fn=_read_tool,
                circuit=cb,
            )

    @pytest.mark.asyncio
    async def test_circuit_opens_after_n_tool_failures(self) -> None:
        from resolute.mcp_servers.base import (
            CircuitBreaker,
            CircuitOpenError,
            CircuitState,
            ToolRisk,
            call_guarded,
        )

        cb = CircuitBreaker("failing", fail_threshold=3)
        token = _make_token()

        for _ in range(3):
            with pytest.raises(RuntimeError):
                await call_guarded(
                    token=token,
                    resource="account",
                    action="read",
                    risk=ToolRisk.READ,
                    tool_name="failing",
                    fn=_failing_tool,
                    circuit=cb,
                )

        assert cb.state == CircuitState.OPEN

        with pytest.raises(CircuitOpenError):
            await call_guarded(
                token=token,
                resource="account",
                action="read",
                risk=ToolRisk.READ,
                tool_name="failing",
                fn=_failing_tool,
                circuit=cb,
            )


# ---------------------------------------------------------------------------
# mcp_tool decorator
# ---------------------------------------------------------------------------


class TestMcpToolDecorator:
    @pytest.mark.asyncio
    async def test_decorator_wires_rbac(self) -> None:
        from resolute.mcp_servers.base import ToolRisk, mcp_tool

        @mcp_tool("account", "read", risk=ToolRisk.READ)
        async def get_account(account_id: str = "a1") -> dict:
            return {"id": account_id}

        token = _make_token(role="support_engineer")
        result = await get_account(token=token, account_id="x")
        assert result["id"] == "x"

    @pytest.mark.asyncio
    async def test_decorator_blocks_wrong_role(self) -> None:
        from resolute.mcp_servers.base import ToolPermissionError, ToolRisk, mcp_tool

        @mcp_tool("invoice", "refund", risk=ToolRisk.WRITE)
        async def refund(invoice_id: str = "i1") -> dict:
            return {"refunded": True}

        token = _make_token(role="contractor")
        with pytest.raises(ToolPermissionError):
            await refund(token=token, invoice_id="i99")

    @pytest.mark.asyncio
    async def test_decorator_attaches_metadata(self) -> None:
        from resolute.mcp_servers.base import ToolRisk, mcp_tool

        @mcp_tool("ticket", "write", risk=ToolRisk.WRITE)
        async def update_ticket() -> None:
            pass

        assert update_ticket.__mcp_resource__ == "ticket"  # type: ignore[attr-defined]
        assert update_ticket.__mcp_action__ == "write"  # type: ignore[attr-defined]
        assert update_ticket.__mcp_risk__ == ToolRisk.WRITE  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_decorator_circuit_per_tool(self) -> None:
        """Each decorated tool gets its own circuit breaker."""
        from resolute.mcp_servers.base import ToolRisk, mcp_tool

        @mcp_tool("account", "read", risk=ToolRisk.READ, fail_threshold=2)
        async def tool_a() -> dict:
            raise RuntimeError("boom")

        @mcp_tool("account", "read", risk=ToolRisk.READ, fail_threshold=2)
        async def tool_b() -> dict:
            return {"ok": True}

        token = _make_token()
        # Trip tool_a's circuit
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await tool_a(token=token)

        # tool_b's circuit must be unaffected
        result = await tool_b(token=token)
        assert result["ok"] is True
