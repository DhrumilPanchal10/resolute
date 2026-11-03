"""Append-only audit log with a SHA-256 hash chain.

Each entry records prev_hash + its own hash = sha256(canonical_row + prev_hash).
verify_chain() recomputes every hash and raises AuditChainError on mismatch,
detecting any tampering with historical rows.

Storage backend is intentionally injected (list by default) so the DB layer
(T2.3) can swap in a Postgres table without changing this module.
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


class AuditChainError(Exception):
    """Raised when verify_chain() detects a tampered or missing row."""


@dataclass
class AuditEntry:
    event_type: str
    actor_id: str
    tenant_id: str
    payload: dict[str, Any]
    occurred_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    prev_hash: str = ""
    hash: str = field(init=False, default="")

    def _canonical(self) -> str:
        """Deterministic serialisation used for hashing (excludes `hash` field)."""
        return json.dumps(
            {
                "event_type": self.event_type,
                "actor_id": self.actor_id,
                "tenant_id": self.tenant_id,
                "payload": self.payload,
                "occurred_at": self.occurred_at,
                "prev_hash": self.prev_hash,
            },
            sort_keys=True,
        )

    def compute_hash(self) -> str:
        return hashlib.sha256(self._canonical().encode()).hexdigest()


class AuditLog:
    """In-memory append-only audit log with hash chain.

    Pass a list-backed store for unit tests; the DB layer (T2.3) will subclass
    or replace this with a Postgres-backed implementation.
    """

    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []

    def append(
        self,
        event_type: str,
        actor_id: str,
        tenant_id: str,
        payload: dict[str, Any],
        occurred_at: str | None = None,
    ) -> AuditEntry:
        prev_hash = self._entries[-1].hash if self._entries else ""
        entry = AuditEntry(
            event_type=event_type,
            actor_id=actor_id,
            tenant_id=tenant_id,
            payload=payload,
            prev_hash=prev_hash,
        )
        if occurred_at is not None:
            entry.occurred_at = occurred_at
        entry.hash = entry.compute_hash()
        self._entries.append(entry)
        return entry

    def entries(self) -> list[AuditEntry]:
        return list(self._entries)

    def verify_chain(self) -> None:
        """Raise AuditChainError if any entry has been tampered with."""
        prev_hash = ""
        for i, entry in enumerate(self._entries):
            expected_prev = prev_hash
            if entry.prev_hash != expected_prev:
                raise AuditChainError(
                    f"Entry {i} prev_hash mismatch: "
                    f"expected {expected_prev!r}, got {entry.prev_hash!r}"
                )
            expected_hash = entry.compute_hash()
            if entry.hash != expected_hash:
                raise AuditChainError(
                    f"Entry {i} hash mismatch: expected {expected_hash!r}, got {entry.hash!r}"
                )
            prev_hash = entry.hash
