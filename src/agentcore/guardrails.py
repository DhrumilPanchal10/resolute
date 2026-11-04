"""
@guarded(node_name) decorator for LangGraph nodes.

Every node in the graph MUST be wrapped with this decorator (AGENTS.md rule).

Pre-checks (run before the node):
  - budget:    run_cost.total_cost_usd >= budget_usd_max
  - loop_count: state["revision_count"] >= MAX_REVISIONS
  - wall_clock: time.monotonic() - state["started_at"] >= WALL_CLOCK_LIMIT_S
  - injection:  untrusted text fields contain prompt-injection patterns

Post-checks (run on the node's output dict):
  - pii_mask:  warn if span/log-visible fields contain PII patterns
  - citations: warn (or block) if resolver/verifier output lacks citations

Policy per check: "warn" logs and continues; "block" returns degraded state.
Blocked/crashed nodes return {"errors": [...], "degraded": True} — never raise.
"""

import logging
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from functools import wraps
from typing import Any

from agentcore.telemetry import span_agent
from resolute.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------


class Policy(StrEnum):
    WARN = "warn"
    BLOCK = "block"


@dataclass(frozen=True)
class CheckResult:
    passed: bool
    check: str
    message: str


# Default policy for each check name.  Overridable at import time by tests.
DEFAULT_POLICIES: dict[str, Policy] = {
    "budget": Policy.BLOCK,
    "loop_count": Policy.BLOCK,
    "wall_clock": Policy.BLOCK,
    "injection": Policy.BLOCK,
    "pii_mask": Policy.WARN,
    "citations": Policy.WARN,
}

# Operational limits (can be overridden via env / tests).
MAX_REVISIONS: int = 2
WALL_CLOCK_LIMIT_S: float = 300.0  # 5 minutes per run

# ---------------------------------------------------------------------------
# Injection screen — v1: pattern + heuristics
# Interface: replace _injection_classifier with a model-based fn later.
# ---------------------------------------------------------------------------

_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"ignore\s+(previous|all|above)\s+(instructions?|prompts?)", re.I),
    re.compile(r"disregard\s+(all|previous|your)\s+", re.I),
    re.compile(r"you\s+are\s+now\s+", re.I),
    re.compile(r"pretend\s+(you\s+are|to\s+be)\s+", re.I),
    re.compile(r"\bSYSTEM\s*:", re.I),
    re.compile(r"<\s*/?system\s*>", re.I),
    re.compile(r"</?(instruction|prompt)s?>", re.I),
    re.compile(r"####\s*(new|override)\s*(system|instruction)", re.I),
    re.compile(r"act\s+as\s+(if\s+you\s+are|a)\s+", re.I),
]

# Fields in the state dict that contain untrusted text (from customers / tools).
_UNTRUSTED_FIELDS: tuple[str, ...] = ("ticket_body", "ticket_title", "tool_output", "message")


def _injection_classifier(text: str) -> bool:
    """Return True if text looks like a prompt-injection attempt."""
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(text):
            return True
    # Heuristic: unusually high ratio of special characters
    if len(text) > 20:
        special = sum(1 for c in text if not c.isalnum() and not c.isspace())
        if special / len(text) > 0.4:
            return True
    return False


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _check_budget(node_name: str, state: dict[str, Any]) -> CheckResult:
    run_cost = state.get("run_cost")
    if run_cost is not None:
        spent = getattr(run_cost, "total_cost_usd", 0.0)
        if spent >= settings.budget_usd_max:
            return CheckResult(
                passed=False,
                check="budget",
                message=f"[{node_name}] budget exceeded: ${spent:.4f} >= ${settings.budget_usd_max:.4f}",
            )
    return CheckResult(passed=True, check="budget", message="")


def _check_loop_count(node_name: str, state: dict[str, Any]) -> CheckResult:
    count = state.get("revision_count", 0)
    if count > MAX_REVISIONS:
        return CheckResult(
            passed=False,
            check="loop_count",
            message=f"[{node_name}] revision_count={count} exceeds MAX_REVISIONS={MAX_REVISIONS}",
        )
    return CheckResult(passed=True, check="loop_count", message="")


def _check_wall_clock(node_name: str, state: dict[str, Any]) -> CheckResult:
    started_at = state.get("started_at")
    if started_at is not None:
        elapsed = time.monotonic() - started_at
        if elapsed >= WALL_CLOCK_LIMIT_S:
            return CheckResult(
                passed=False,
                check="wall_clock",
                message=f"[{node_name}] wall_clock {elapsed:.1f}s >= limit {WALL_CLOCK_LIMIT_S}s",
            )
    return CheckResult(passed=True, check="wall_clock", message="")


def _check_injection(node_name: str, state: dict[str, Any]) -> CheckResult:
    for field_name in _UNTRUSTED_FIELDS:
        value = state.get(field_name)
        if isinstance(value, str) and _injection_classifier(value):
            return CheckResult(
                passed=False,
                check="injection",
                message=f"[{node_name}] injection pattern detected in field '{field_name}'",
            )
    return CheckResult(passed=True, check="injection", message="")


# ---------------------------------------------------------------------------
# Post-checks (operate on the node's output dict)
# ---------------------------------------------------------------------------

_PII_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),  # SSN
    re.compile(r"\b4[0-9]{12}(?:[0-9]{3})?\b"),  # Visa card (simple)
    re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Z|a-z]{2,}\b"),  # email
]


def _check_pii_mask(node_name: str, output: dict[str, Any]) -> CheckResult:
    """Warn if any output field looks like it contains raw PII."""
    for key, value in output.items():
        if isinstance(value, str):
            for pattern in _PII_PATTERNS:
                if pattern.search(value):
                    return CheckResult(
                        passed=False,
                        check="pii_mask",
                        message=f"[{node_name}] possible PII in output field '{key}' — mask before logging",
                    )
    return CheckResult(passed=True, check="pii_mask", message="")


_CITATION_NODES: frozenset[str] = frozenset({"resolver", "verifier", "knowledge"})


def _check_citations(node_name: str, output: dict[str, Any]) -> CheckResult:
    if node_name not in _CITATION_NODES:
        return CheckResult(passed=True, check="citations", message="")
    draft = output.get("draft", "") or ""
    evidence = output.get("evidence", [])
    if isinstance(draft, str) and len(draft) > 50 and not evidence:
        return CheckResult(
            passed=False,
            check="citations",
            message=f"[{node_name}] draft produced but evidence list is empty",
        )
    return CheckResult(passed=True, check="citations", message="")


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------

_PRE_CHECKS: list[Callable[[str, dict[str, Any]], CheckResult]] = [
    _check_budget,
    _check_loop_count,
    _check_wall_clock,
    _check_injection,
]

_POST_CHECKS: list[Callable[[str, dict[str, Any]], CheckResult]] = [
    _check_pii_mask,
    _check_citations,
]

NodeFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def guarded(
    node_name: str, policies: dict[str, Policy] | None = None
) -> Callable[[NodeFn], NodeFn]:
    """Decorator that wraps a LangGraph node with pre- and post-checks.

    Args:
        node_name: Identifies the node in log messages and check output.
        policies:  Per-check policy overrides (defaults to DEFAULT_POLICIES).
    """
    effective = {**DEFAULT_POLICIES, **(policies or {})}

    def decorator(fn: NodeFn) -> NodeFn:
        @wraps(fn)
        async def wrapper(state: dict[str, Any]) -> dict[str, Any]:
            errors: list[str] = []

            # --- Pre-checks ---
            for check_fn in _PRE_CHECKS:
                result = check_fn(node_name, state)
                if not result.passed:
                    policy = effective.get(result.check, Policy.BLOCK)
                    if policy == Policy.BLOCK:
                        return {"errors": [result.message], "degraded": True}
                    logger.warning("guardrails warn: %s", result.message)
                    errors.append(result.message)

            # --- Node execution (never lets exceptions escape) ---
            async with span_agent(
                node_name,
                tenant_id=state.get("tenant_id", ""),
                ticket_id=state.get("ticket_id", ""),
            ) as span:
                try:
                    output: dict[str, Any] = await fn(state)
                except Exception as exc:
                    msg = f"[{node_name}] node raised {type(exc).__name__}: {exc}"
                    logger.error("guardrails caught: %s", msg)
                    return {"errors": [msg], "degraded": True}

                # --- Post-checks ---
                for check_fn in _POST_CHECKS:
                    result = check_fn(node_name, output)
                    if not result.passed:
                        policy = effective.get(result.check, Policy.WARN)
                        if policy == Policy.BLOCK:
                            span.set_attribute("resolute.degraded", True)
                            return {"errors": [result.message], "degraded": True}
                        logger.warning("guardrails warn: %s", result.message)

                if errors:
                    existing = output.get("errors", [])
                    output["errors"] = existing + errors

                return output

        return wrapper

    return decorator
