"""Shared infrastructure for all Resolute MCP tool servers.

Every tool server wires its tools through `call_guarded()` or the
`mcp_tool()` decorator, which enforces:

  1. JWT verification  (agentcore.auth.verify_jwt)
  2. RBAC check        (agentcore.auth.has_permission)
  3. Circuit breaker   (open after N consecutive errors)
  4. Timeout           (asyncio.wait_for)
  5. Audit event       (agentcore.audit.AuditLog append)
  6. Span emission     (lightweight dict; wired to OTLP in T2.1)

Risk levels (declared per tool):
  READ        — no side effects; contactor + all roles allowed
  WRITE       — mutates state; support_engineer + above
  DESTRUCTIVE — irreversible; requires lead / admin + explicit approval_token
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from functools import wraps
from typing import Any

from agentcore.audit import AuditLog
from agentcore.auth import AuthError, UserClaims, has_permission, verify_jwt
from agentcore.errors import ResoluteError

# ---------------------------------------------------------------------------
# Tool risk levels
# ---------------------------------------------------------------------------


class ToolRisk(StrEnum):
    READ = "read"
    WRITE = "write"
    DESTRUCTIVE = "destructive"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ToolPermissionError(ResoluteError):
    """Raised when a JWT is missing/invalid or the role is insufficient."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class CircuitOpenError(ResoluteError):
    """Raised when the circuit breaker is open (tool is failing repeatedly)."""

    def __init__(self, tool_name: str) -> None:
        super().__init__(f"circuit open for tool {tool_name!r}")
        self.tool_name = tool_name


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------

_DEFAULT_FAIL_THRESHOLD = 5
_DEFAULT_RESET_TIMEOUT_S = 60.0


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    """Per-tool circuit breaker.

    State machine:
      CLOSED  → (N consecutive failures) → OPEN
      OPEN    → (after reset_timeout_s)  → HALF_OPEN
      HALF_OPEN → (success)              → CLOSED
      HALF_OPEN → (failure)              → OPEN
    """

    tool_name: str
    fail_threshold: int = _DEFAULT_FAIL_THRESHOLD
    reset_timeout_s: float = _DEFAULT_RESET_TIMEOUT_S

    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _consecutive_failures: int = field(default=0, init=False)
    _opened_at: float = field(default=0.0, init=False)

    @property
    def state(self) -> CircuitState:
        if (
            self._state == CircuitState.OPEN
            and time.monotonic() - self._opened_at >= self.reset_timeout_s
        ):
            self._state = CircuitState.HALF_OPEN
        return self._state

    def record_success(self) -> None:
        self._consecutive_failures = 0
        self._state = CircuitState.CLOSED

    def record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.fail_threshold:
            self._state = CircuitState.OPEN
            self._opened_at = time.monotonic()

    def allow_request(self) -> bool:
        s = self.state
        return s in (CircuitState.CLOSED, CircuitState.HALF_OPEN)


# ---------------------------------------------------------------------------
# Lightweight span (wired to OTLP in T2.1)
# ---------------------------------------------------------------------------


@dataclass
class ToolSpan:
    tool_name: str
    tenant_id: str
    user_id: str
    risk: str
    duration_ms: float = 0.0
    success: bool = True
    error: str = ""


# ---------------------------------------------------------------------------
# Core guarded call
# ---------------------------------------------------------------------------


async def call_guarded(
    *,
    token: str,
    resource: str,
    action: str,
    risk: ToolRisk,
    tool_name: str,
    fn: Callable[..., Any],
    audit_log: AuditLog | None = None,
    circuit: CircuitBreaker | None = None,
    timeout_s: float = 30.0,
    span_sink: list[ToolSpan] | None = None,
    **kwargs: Any,
) -> Any:
    """Execute a tool function with all cross-cutting concerns applied.

    Args:
        token:      Raw Bearer JWT string (empty string for unauthenticated).
        resource:   RBAC resource name (e.g. "account").
        action:     RBAC action name (e.g. "read").
        risk:       ToolRisk level declared by the tool.
        tool_name:  Human-readable tool name (for audit + circuit breaker).
        fn:         The async tool function to call.
        audit_log:  AuditLog instance; writes start + result events.
        circuit:    CircuitBreaker instance for this tool.
        timeout_s:  asyncio.wait_for timeout in seconds.
        span_sink:  List to append ToolSpan to (testing hook; real OTLP in T2.1).
        **kwargs:   Passed through to fn.

    Raises:
        ToolPermissionError: JWT invalid, missing, or role insufficient.
        CircuitOpenError:    Circuit breaker is open.
        asyncio.TimeoutError: fn exceeded timeout_s.
    """
    # 1. JWT verification
    if not token:
        raise ToolPermissionError("missing Authorization token")
    try:
        claims: UserClaims = verify_jwt(token)
    except AuthError as exc:
        raise ToolPermissionError(str(exc)) from exc

    # 2. RBAC check
    if not has_permission(claims.role, resource, action):
        raise ToolPermissionError(f"role {claims.role!r} may not perform {resource}.{action}")

    # 3. Circuit breaker
    if circuit is not None and not circuit.allow_request():
        raise CircuitOpenError(tool_name)

    # 4. Pre-audit
    if audit_log is not None:
        audit_log.append(
            event_type="tool_call_start",
            actor_id=claims.user_id,
            tenant_id=claims.tenant_id,
            payload={
                "tool": tool_name,
                "resource": resource,
                "action": action,
                "risk": str(risk),
            },
        )

    t0 = time.perf_counter()
    span = ToolSpan(
        tool_name=tool_name,
        tenant_id=claims.tenant_id,
        user_id=claims.user_id,
        risk=str(risk),
    )
    try:
        result = await asyncio.wait_for(fn(**kwargs), timeout=timeout_s)
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        span.duration_ms = elapsed_ms
        span.success = False
        span.error = type(exc).__name__
        if span_sink is not None:
            span_sink.append(span)
        if circuit is not None:
            circuit.record_failure()
        if audit_log is not None:
            audit_log.append(
                event_type="tool_call_error",
                actor_id=claims.user_id,
                tenant_id=claims.tenant_id,
                payload={"tool": tool_name, "error": str(exc)},
            )
        raise

    elapsed_ms = (time.perf_counter() - t0) * 1000
    span.duration_ms = elapsed_ms
    if span_sink is not None:
        span_sink.append(span)
    if circuit is not None:
        circuit.record_success()
    if audit_log is not None:
        audit_log.append(
            event_type="tool_call_success",
            actor_id=claims.user_id,
            tenant_id=claims.tenant_id,
            payload={"tool": tool_name},
        )
    return result


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------


def mcp_tool(
    resource: str,
    action: str,
    *,
    risk: ToolRisk = ToolRisk.READ,
    timeout_s: float = 30.0,
    fail_threshold: int = _DEFAULT_FAIL_THRESHOLD,
    reset_timeout_s: float = _DEFAULT_RESET_TIMEOUT_S,
    audit_log: AuditLog | None = None,
    span_sink: list[ToolSpan] | None = None,
) -> Callable:
    """Decorator factory for guarded MCP tool functions.

    The decorated function must be async and will receive a `token: str = ""`
    keyword argument that the MCP server extracts from the Authorization header.
    All other kwargs are passed through to the original function.

    Usage::

        log = AuditLog()

        @mcp_tool("account", "read", risk=ToolRisk.READ, audit_log=log)
        async def get_account(account_id: str) -> dict:
            ...
    """

    def decorator(fn: Callable) -> Callable:
        circuit = CircuitBreaker(
            tool_name=fn.__name__,
            fail_threshold=fail_threshold,
            reset_timeout_s=reset_timeout_s,
        )
        _audit = audit_log
        _sink = span_sink

        @wraps(fn)
        async def wrapper(token: str = "", **kwargs: Any) -> Any:
            return await call_guarded(
                token=token,
                resource=resource,
                action=action,
                risk=risk,
                tool_name=fn.__name__,
                fn=fn,
                audit_log=_audit,
                circuit=circuit,
                timeout_s=timeout_s,
                span_sink=_sink,
                **kwargs,
            )

        # Attach metadata for introspection
        wrapper.__mcp_resource__ = resource  # type: ignore[attr-defined]
        wrapper.__mcp_action__ = action  # type: ignore[attr-defined]
        wrapper.__mcp_risk__ = risk  # type: ignore[attr-defined]
        wrapper.__mcp_circuit__ = circuit  # type: ignore[attr-defined]
        return wrapper

    return decorator
