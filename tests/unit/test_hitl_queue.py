"""Offline unit tests for hitl/queue.py and hitl/policies.py (T6.2)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from resolute.hitl.policies import (
    OWNERSHIP_ACTIONS,
    REFUND_THRESHOLD_USD,
    required_approver_role,
    requires_approval,
)
from resolute.hitl.queue import (
    ApprovalItem,
    ApprovalQueue,
    Override,
    load_override,
    save_override,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _item(
    ticket_id: str = "t1",
    severity: str = "high",
    tier: str = "default",
    action_type: str = "refund_invoice",
    required_role: str = "lead",
    created_at: float | None = None,
) -> ApprovalItem:
    return ApprovalItem(
        ticket_id=ticket_id,
        tenant_id="tenant-1",
        action_type=action_type,
        args={"amount_usd": 600},
        required_role=required_role,
        severity=severity,
        tier=tier,
        created_at=created_at if created_at is not None else time.monotonic(),
    )


# ---------------------------------------------------------------------------
# Policy tests (extend T5.7 coverage)
# ---------------------------------------------------------------------------


def test_requires_approval_refund_above_threshold():
    assert requires_approval("refund_invoice", {"amount_usd": REFUND_THRESHOLD_USD + 1})


def test_requires_approval_refund_at_threshold():
    assert not requires_approval("refund_invoice", {"amount_usd": REFUND_THRESHOLD_USD})


def test_requires_approval_config_change():
    assert requires_approval("config_change", {})


def test_requires_approval_ownership():
    for action in OWNERSHIP_ACTIONS:
        assert requires_approval(action, {})


def test_requires_approval_reply_only():
    assert not requires_approval("reply_only", {})


def test_required_approver_config_change():
    assert required_approver_role("config_change", {}) == "admin"


def test_required_approver_ownership():
    assert required_approver_role("transfer_ownership", {}) == "lead"


def test_required_approver_refund():
    assert required_approver_role("refund_invoice", {}) == "lead"


def test_required_approver_default():
    assert required_approver_role("reply_only", {}) == "support_engineer"


# ---------------------------------------------------------------------------
# ApprovalQueue — ordering
# ---------------------------------------------------------------------------


def test_queue_sorts_by_severity():
    q = ApprovalQueue()
    q.enqueue(_item("t-low", severity="low", created_at=1.0))
    q.enqueue(_item("t-crit", severity="critical", created_at=2.0))
    q.enqueue(_item("t-high", severity="high", created_at=3.0))

    items = q.peek()
    assert [i.ticket_id for i in items] == ["t-crit", "t-high", "t-low"]


def test_queue_sorts_by_tier_within_same_severity():
    q = ApprovalQueue()
    q.enqueue(_item("t-small", severity="high", tier="small", created_at=1.0))
    q.enqueue(_item("t-strong", severity="high", tier="strong", created_at=2.0))
    q.enqueue(_item("t-default", severity="high", tier="default", created_at=3.0))

    items = q.peek()
    assert [i.ticket_id for i in items] == ["t-strong", "t-default", "t-small"]


def test_queue_oldest_first_within_same_severity_and_tier():
    t0 = time.monotonic()
    q = ApprovalQueue()
    q.enqueue(_item("t-later", severity="high", tier="default", created_at=t0 + 10))
    q.enqueue(_item("t-older", severity="high", tier="default", created_at=t0 + 1))

    items = q.peek()
    assert items[0].ticket_id == "t-older"


def test_queue_len_and_bool():
    q = ApprovalQueue()
    assert len(q) == 0
    assert not q
    q.enqueue(_item("t1"))
    assert len(q) == 1
    assert q


def test_queue_dequeue_removes_item():
    q = ApprovalQueue()
    q.enqueue(_item("t1"))
    q.enqueue(_item("t2"))

    removed = q.dequeue("t1")
    assert removed is not None
    assert removed.ticket_id == "t1"
    assert len(q) == 1


def test_queue_dequeue_missing_returns_none():
    q = ApprovalQueue()
    assert q.dequeue("no-such-ticket") is None


# ---------------------------------------------------------------------------
# ApprovalQueue — role filtering
# ---------------------------------------------------------------------------


def test_peek_lead_sees_lead_and_support_items():
    q = ApprovalQueue()
    q.enqueue(_item("t-admin-only", required_role="admin"))
    q.enqueue(_item("t-lead", required_role="lead"))
    q.enqueue(_item("t-se", required_role="support_engineer"))

    visible = q.peek(role="lead")
    ids = {i.ticket_id for i in visible}
    assert "t-lead" in ids
    assert "t-se" in ids
    # lead cannot approve admin-only tasks
    assert "t-admin-only" not in ids


def test_peek_admin_sees_all():
    q = ApprovalQueue()
    q.enqueue(_item("t-admin-only", required_role="admin"))
    q.enqueue(_item("t-lead", required_role="lead"))

    visible = q.peek(role="admin")
    assert len(visible) == 2


def test_peek_support_engineer_sees_only_own():
    q = ApprovalQueue()
    q.enqueue(_item("t-lead", required_role="lead"))
    q.enqueue(_item("t-se", required_role="support_engineer"))

    visible = q.peek(role="support_engineer")
    ids = {i.ticket_id for i in visible}
    assert "t-se" in ids
    assert "t-lead" not in ids


def test_peek_no_role_returns_all():
    q = ApprovalQueue()
    q.enqueue(_item("t-admin", required_role="admin"))
    q.enqueue(_item("t-lead", required_role="lead"))

    assert len(q.peek()) == 2


# ---------------------------------------------------------------------------
# Override persistence
# ---------------------------------------------------------------------------


def test_save_and_load_override(tmp_path: Path):
    override = Override(
        ticket_id="ticket-999",
        action_type="refund_invoice",
        args={"amount_usd": 750, "invoice_id": "inv-01"},
        decision="approve",
        reason="Confirmed duplicate charge",
        approver_role="lead",
        created_at="2026-11-03T12:00:00Z",
    )

    dest = save_override(override, overrides_dir=tmp_path)
    assert dest.exists()

    loaded = load_override("ticket-999", overrides_dir=tmp_path)
    assert loaded is not None
    assert loaded.ticket_id == "ticket-999"
    assert loaded.decision == "approve"
    assert loaded.reason == "Confirmed duplicate charge"
    assert loaded.args["amount_usd"] == 750


def test_load_missing_override_returns_none(tmp_path: Path):
    assert load_override("no-such-ticket", overrides_dir=tmp_path) is None


def test_save_override_creates_dir(tmp_path: Path):
    sub = tmp_path / "new_subdir"
    assert not sub.exists()
    override = Override(
        ticket_id="t1",
        action_type="issue_credit",
        args={},
        decision="reject",
        reason="Insufficient evidence",
        approver_role="admin",
        created_at="2026-11-03T13:00:00Z",
    )
    save_override(override, overrides_dir=sub)
    assert sub.exists()
    assert (sub / "t1.json").exists()


def test_override_json_format(tmp_path: Path):
    import json as _json

    override = Override(
        ticket_id="fmt-test",
        action_type="close_account",
        args={"account_id": "acct-1"},
        decision="approve",
        reason="Customer request",
        approver_role="lead",
        created_at="2026-11-03T14:00:00Z",
    )
    dest = save_override(override, overrides_dir=tmp_path)
    data = _json.loads(dest.read_text())
    assert data["ticket_id"] == "fmt-test"
    assert data["decision"] == "approve"
    assert "args" in data
