"""HITL (Human-in-the-Loop) policy definitions.

A policy maps an action type + args to a required approver role.
`requires_approval(action_type, args)` returns `True` when the action must
be held for human review before execution.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Policy table
# ---------------------------------------------------------------------------

#: Refunds or credits above this amount require a lead/admin to approve.
REFUND_THRESHOLD_USD: float = 500.0

#: Config changes always require admin approval.
CONFIG_CHANGE_ACTIONS: frozenset[str] = frozenset({"config_change"})

#: Ownership/account reassignment requires lead approval.
OWNERSHIP_ACTIONS: frozenset[str] = frozenset({"transfer_ownership", "close_account"})


def requires_approval(action_type: str, args: dict[str, Any]) -> bool:
    """Return True when this action must wait for a human approver."""
    if action_type in CONFIG_CHANGE_ACTIONS:
        return True
    if action_type in OWNERSHIP_ACTIONS:
        return True
    if action_type in ("refund_invoice", "issue_credit"):
        amount = float(args.get("amount_usd", 0))
        if amount > REFUND_THRESHOLD_USD:
            return True
    return False


def required_approver_role(action_type: str, args: dict[str, Any]) -> str:
    """Return the minimum role that may approve this action."""
    if action_type in CONFIG_CHANGE_ACTIONS:
        return "admin"
    if action_type in OWNERSHIP_ACTIONS:
        return "lead"
    if action_type in ("refund_invoice", "issue_credit"):
        return "lead"
    return "support_engineer"
