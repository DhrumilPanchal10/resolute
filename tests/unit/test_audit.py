"""Tests for agentcore.audit hash-chain integrity."""

import pytest

from agentcore.audit import AuditChainError, AuditLog


def _log_with_entries(n: int) -> AuditLog:
    log = AuditLog()
    for i in range(n):
        log.append(
            event_type="test.event",
            actor_id="user-1",
            tenant_id="tenant-a",
            payload={"index": i},
        )
    return log


class TestAuditAppend:
    def test_first_entry_has_empty_prev_hash(self) -> None:
        log = _log_with_entries(1)
        assert log.entries()[0].prev_hash == ""

    def test_chain_links_correctly(self) -> None:
        log = _log_with_entries(3)
        entries = log.entries()
        assert entries[1].prev_hash == entries[0].hash
        assert entries[2].prev_hash == entries[1].hash

    def test_hash_is_deterministic(self) -> None:
        log = AuditLog()
        e = log.append("ev", "a", "t", {}, occurred_at="2026-01-01T00:00:00+00:00")
        assert e.hash == e.compute_hash()


class TestVerifyChain:
    def test_valid_chain_passes(self) -> None:
        log = _log_with_entries(5)
        log.verify_chain()  # must not raise

    def test_tampered_payload_detected(self) -> None:
        log = _log_with_entries(3)
        # Silently mutate an entry's payload (simulating DB tampering)
        log.entries()[1].payload["injected"] = "evil"
        with pytest.raises(AuditChainError, match="hash mismatch"):
            log.verify_chain()

    def test_tampered_prev_hash_detected(self) -> None:
        log = _log_with_entries(3)
        log.entries()[2].prev_hash = "0" * 64
        with pytest.raises(AuditChainError, match="prev_hash mismatch"):
            log.verify_chain()

    def test_tampered_hash_field_detected(self) -> None:
        log = _log_with_entries(2)
        log.entries()[0].hash = "deadbeef"
        with pytest.raises(AuditChainError):
            log.verify_chain()

    def test_empty_log_passes(self) -> None:
        AuditLog().verify_chain()
