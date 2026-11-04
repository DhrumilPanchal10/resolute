"""Prompt caching utilities.

Stable system prefixes are placed first in messages to maximize cache hits
with providers that support prompt caching (Anthropic, Gemini, etc.).

The key principle: system messages that are identical across calls should be
at the start of the messages list, so the provider's KV-cache can reuse them.

Functions:
  - build_cached_messages(): constructs messages with stable prefix first
  - estimate_prefix_tokens(): estimates cacheable prefix size
  - CostTracker: measures cost per resolved ticket with before/after comparison
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any


def build_cached_messages(
    system_prompt: str,
    user_content: str,
    *,
    context_blocks: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Build a messages list with stable prefix for prompt caching.

    The system prompt (stable across calls) comes first, followed by
    any context blocks, then the user message (variable per call).
    This ordering maximizes KV-cache reuse.

    Args:
        system_prompt: Stable system instructions (cacheable).
        user_content: Per-call user message (variable).
        context_blocks: Optional additional system-level context
                       (e.g. tool descriptions, retrieved docs).
    """
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
    ]
    if context_blocks:
        for block in context_blocks:
            messages.append(block)
    messages.append({"role": "user", "content": user_content})
    return messages


def estimate_prefix_tokens(system_prompt: str, context_blocks: list[dict[str, str]] | None = None) -> int:
    """Rough token estimate for the cacheable prefix.

    Uses ~4 chars per token as a heuristic (good enough for cost estimation).
    """
    chars = len(system_prompt)
    if context_blocks:
        for block in context_blocks:
            chars += len(block.get("content", ""))
    return chars // 4


def prefix_hash(system_prompt: str) -> str:
    """Hash a system prompt to detect when the prefix changes (cache invalidation)."""
    return hashlib.sha256(system_prompt.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Per-node routing configuration
# ---------------------------------------------------------------------------

NODE_TIER_MAP: dict[str, str] = {
    "triage": "small",
    "knowledge": "small",
    "investigator": "strong",
    "resolver": "strong",
    "verifier": "small",
}


def tier_for_node(node_name: str, route_override: str | None = None) -> str:
    """Return the model tier for a graph node.

    Priority:
      1. route_override from triage (dynamic per-ticket)
      2. Static NODE_TIER_MAP (tuned defaults)
      3. "small" fallback
    """
    if route_override and route_override in ("small", "default", "strong"):
        # Allow triage to override, but only upgrade (not downgrade)
        default = NODE_TIER_MAP.get(node_name, "small")
        tier_order = {"small": 0, "default": 1, "strong": 2}
        if tier_order.get(route_override, 0) > tier_order.get(default, 0):
            return route_override
    return NODE_TIER_MAP.get(node_name, "small")


# ---------------------------------------------------------------------------
# Cost measurement
# ---------------------------------------------------------------------------


@dataclass
class CostTracker:
    """Tracks cost per resolved ticket for before/after comparison."""

    label: str = "default"
    _tickets: dict[str, list[dict[str, float]]] = field(default_factory=dict)

    def record_call(
        self,
        ticket_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        cached_tokens: int = 0,
    ) -> None:
        if ticket_id not in self._tickets:
            self._tickets[ticket_id] = []
        self._tickets[ticket_id].append({
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost_usd,
            "cached_tokens": cached_tokens,
        })

    @property
    def total_tickets(self) -> int:
        return len(self._tickets)

    @property
    def total_cost(self) -> float:
        return sum(
            c["cost_usd"]
            for calls in self._tickets.values()
            for c in calls
        )

    @property
    def avg_cost_per_ticket(self) -> float:
        if not self._tickets:
            return 0.0
        return self.total_cost / len(self._tickets)

    @property
    def total_tokens(self) -> int:
        return sum(
            int(c["input_tokens"] + c["output_tokens"])
            for calls in self._tickets.values()
            for c in calls
        )

    @property
    def total_cached_tokens(self) -> int:
        return sum(
            int(c.get("cached_tokens", 0))
            for calls in self._tickets.values()
            for c in calls
        )

    @property
    def cache_hit_ratio(self) -> float:
        total_in = sum(
            int(c["input_tokens"])
            for calls in self._tickets.values()
            for c in calls
        )
        if total_in == 0:
            return 0.0
        return self.total_cached_tokens / total_in

    def compare(self, other: CostTracker) -> dict[str, Any]:
        """Compare this tracker (before) with another (after)."""
        return {
            "before": {
                "label": self.label,
                "tickets": self.total_tickets,
                "total_cost": self.total_cost,
                "avg_cost_per_ticket": self.avg_cost_per_ticket,
                "total_tokens": self.total_tokens,
                "cached_tokens": self.total_cached_tokens,
                "cache_hit_ratio": self.cache_hit_ratio,
            },
            "after": {
                "label": other.label,
                "tickets": other.total_tickets,
                "total_cost": other.total_cost,
                "avg_cost_per_ticket": other.avg_cost_per_ticket,
                "total_tokens": other.total_tokens,
                "cached_tokens": other.total_cached_tokens,
                "cache_hit_ratio": other.cache_hit_ratio,
            },
            "cost_reduction": (
                (self.avg_cost_per_ticket - other.avg_cost_per_ticket) / self.avg_cost_per_ticket
                if self.avg_cost_per_ticket > 0 else 0.0
            ),
            "token_reduction": (
                (self.total_tokens - other.total_tokens) / self.total_tokens
                if self.total_tokens > 0 else 0.0
            ),
        }
