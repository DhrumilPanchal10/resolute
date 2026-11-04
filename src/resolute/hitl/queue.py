"""HITL approval queue — ordered by severity, model tier, then age.

Design
------
- ApprovalItem holds everything a reviewer needs: ticket metadata, the
  pending action, the required approver role, and when it arrived.
- ApprovalQueue keeps items sorted; `peek(role)` returns only items the
  caller's role may approve so reviewers never see tasks above their clearance.
- Override decisions are persisted to `evals/data/overrides/{ticket_id}.json`
  for use in evaluation runs (a human-labelled ground-truth corpus).

Sort key
--------
  (severity_rank, tier_rank, created_at)
  — critical > high > medium > low
  — strong > default > small
  — oldest first (smallest monotonic timestamp)

Thread safety
-------------
Single-process asyncio only.  For multi-process deployments, replace the
in-memory list with a Postgres advisory-lock queue or a Redis sorted set.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Ordering maps
# ---------------------------------------------------------------------------

_SEVERITY_RANK: dict[str, int] = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
}

_TIER_RANK: dict[str, int] = {
    "strong": 0,
    "default": 1,
    "small": 2,
}

# Minimum severity rank that each role may approve (lower rank = more critical).
# A role can approve items whose severity_rank >= its threshold.
# Leads approve high + medium + low; admins approve everything.
_ROLE_MAX_RANK: dict[str, int] = {
    "admin": 0,          # can approve all
    "lead": 1,           # high, medium, low
    "support_engineer": 2,  # medium, low only
}

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(order=False)
class ApprovalItem:
    """A single pending approval request."""

    ticket_id: str
    tenant_id: str
    action_type: str
    args: dict[str, Any]
    required_role: str    # minimum role needed: "admin" | "lead" | "support_engineer"
    severity: str         # from triage: critical | high | medium | low
    tier: str             # from triage: strong | default | small
    interrupt_payload: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.monotonic)

    # ---- sort helpers ----

    @property
    def _sort_key(self) -> tuple[int, int, float]:
        return (
            _SEVERITY_RANK.get(self.severity, 99),
            _TIER_RANK.get(self.tier, 99),
            self.created_at,
        )

    def __lt__(self, other: ApprovalItem) -> bool:
        return self._sort_key < other._sort_key


# ---------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------


class ApprovalQueue:
    """In-memory HITL approval queue, sorted by (severity, tier, age)."""

    def __init__(self) -> None:
        self._items: list[ApprovalItem] = []

    # ---- write ----

    def enqueue(self, item: ApprovalItem) -> None:
        """Add an item and keep the list sorted."""
        import bisect

        bisect.insort(self._items, item)

    def dequeue(self, ticket_id: str) -> ApprovalItem | None:
        """Remove and return the item for `ticket_id`, or None if not found."""
        for i, item in enumerate(self._items):
            if item.ticket_id == ticket_id:
                return self._items.pop(i)
        return None

    # ---- read ----

    def peek(self, role: str | None = None) -> list[ApprovalItem]:
        """Return all pending items, optionally filtered to ones `role` may approve.

        A role may approve an item when the item's required_role rank >=
        the role's minimum clearance rank.
        """
        if role is None:
            return list(self._items)

        role_clearance = _ROLE_MAX_RANK.get(role, 99)
        return [
            item
            for item in self._items
            if _ROLE_MAX_RANK.get(item.required_role, 99) >= role_clearance
        ]

    def __len__(self) -> int:
        return len(self._items)

    def __bool__(self) -> bool:
        return bool(self._items)


# ---------------------------------------------------------------------------
# Override persistence
# ---------------------------------------------------------------------------


@dataclass
class Override:
    """A human reviewer's decision on a pending action — saved for eval use."""

    ticket_id: str
    action_type: str
    args: dict[str, Any]
    decision: str          # "approve" | "reject"
    reason: str
    approver_role: str
    created_at: str        # ISO-8601 string


def save_override(
    override: Override,
    overrides_dir: Path | None = None,
) -> Path:
    """Persist an override decision to `overrides_dir/{ticket_id}.json`.

    Args:
        override:      The decision record to save.
        overrides_dir: Directory to write to.  Defaults to
                       `<repo-root>/evals/data/overrides/`.
    Returns:
        The path the file was written to.
    """
    if overrides_dir is None:
        overrides_dir = Path(__file__).parents[4] / "evals" / "data" / "overrides"
    overrides_dir.mkdir(parents=True, exist_ok=True)

    dest = overrides_dir / f"{override.ticket_id}.json"
    dest.write_text(
        json.dumps(
            {
                "ticket_id": override.ticket_id,
                "action_type": override.action_type,
                "args": override.args,
                "decision": override.decision,
                "reason": override.reason,
                "approver_role": override.approver_role,
                "created_at": override.created_at,
            },
            indent=2,
        )
    )
    return dest


def load_override(ticket_id: str, overrides_dir: Path | None = None) -> Override | None:
    """Load a single override from disk, or None if it doesn't exist."""
    if overrides_dir is None:
        overrides_dir = Path(__file__).parents[4] / "evals" / "data" / "overrides"
    dest = overrides_dir / f"{ticket_id}.json"
    if not dest.exists():
        return None
    data = json.loads(dest.read_text())
    return Override(**data)
