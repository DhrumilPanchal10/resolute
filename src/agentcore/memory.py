"""Three-tier memory system for the Resolute agent graph.

ShortTerm  — in-thread message buffer with token-based compaction.
LongTerm   — per-customer fact store; write() rejects untrusted sources.
Episodic   — resolved-ticket memories with embeddings, TTL, and supersession;
             retrieve() filters by tenant + similarity; consolidate() clusters
             into known-issue notes.

All retrieval is tenant-scoped — cross-tenant leakage is structurally impossible.
"""

import math
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class MemorySourceError(ValueError):
    """Raised when LongTerm.write() receives an untrusted source."""


# ---------------------------------------------------------------------------
# Token estimation (character heuristic — no heavy dep needed here)
# ---------------------------------------------------------------------------


def _estimate_tokens(text: str) -> int:
    """Rough estimate: 1 token ≈ 4 characters."""
    return max(1, len(text) // 4)


def _message_tokens(msg: dict[str, Any]) -> int:
    return _estimate_tokens(str(msg.get("content", "")))


# ---------------------------------------------------------------------------
# Cosine similarity (pure Python — avoids numpy at import time)
# ---------------------------------------------------------------------------


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    return dot / (mag_a * mag_b)


# ---------------------------------------------------------------------------
# ShortTerm
# ---------------------------------------------------------------------------


class ShortTerm:
    """Rolling message buffer for the current thread.

    When estimated tokens exceed MAX_TOKENS, maybe_compact() calls the
    provided async summarise_fn to compress older messages into one summary
    message, keeping the most recent TAIL_KEEP messages verbatim.
    """

    MAX_TOKENS: int = 2_000
    TAIL_KEEP: int = 4  # always keep this many recent messages verbatim

    def __init__(self) -> None:
        self._messages: list[dict[str, Any]] = []

    def add(self, message: dict[str, Any]) -> None:
        self._messages.append(message)

    def messages(self) -> list[dict[str, Any]]:
        return list(self._messages)

    def estimated_tokens(self) -> int:
        return sum(_message_tokens(m) for m in self._messages)

    async def maybe_compact(
        self,
        summarise_fn: Callable[[list[dict[str, Any]]], Awaitable[str]],
    ) -> bool:
        """Compact if over token limit.  Returns True if compaction ran."""
        if self.estimated_tokens() <= self.MAX_TOKENS:
            return False

        tail = self._messages[-self.TAIL_KEEP :]
        to_summarise = self._messages[: -self.TAIL_KEEP]
        if not to_summarise:
            return False

        summary_text = await summarise_fn(to_summarise)
        self._messages = [{"role": "assistant", "content": summary_text}] + tail
        return True


# ---------------------------------------------------------------------------
# LongTerm
# ---------------------------------------------------------------------------


ALLOWED_LONG_TERM_SOURCES: frozenset[str] = frozenset({"system_data", "verified_outcome"})


@dataclass
class LongTermFact:
    key: str
    value: str
    source: str
    written_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class LongTerm:
    """Per-customer fact store, scoped by tenant.

    write() enforces that only trusted sources may add facts.
    Customer-supplied text is NEVER a valid source.
    """

    def __init__(self) -> None:
        # {(tenant_id, customer_id): {key: LongTermFact}}
        self._store: dict[tuple[str, str], dict[str, LongTermFact]] = {}

    def write(
        self,
        *,
        tenant_id: str,
        customer_id: str,
        key: str,
        value: str,
        source: str,
    ) -> LongTermFact:
        if source not in ALLOWED_LONG_TERM_SOURCES:
            raise MemorySourceError(
                f"Source {source!r} is not trusted for LongTerm writes. "
                f"Allowed: {sorted(ALLOWED_LONG_TERM_SOURCES)}"
            )
        scope = (tenant_id, customer_id)
        if scope not in self._store:
            self._store[scope] = {}
        fact = LongTermFact(key=key, value=value, source=source)
        self._store[scope][key] = fact
        return fact

    def get(self, *, tenant_id: str, customer_id: str) -> dict[str, LongTermFact]:
        """Return all facts for customer within tenant.  Cross-tenant: empty dict."""
        return dict(self._store.get((tenant_id, customer_id), {}))


# ---------------------------------------------------------------------------
# Episodic
# ---------------------------------------------------------------------------


@dataclass
class EpisodicMemory:
    id: str
    tenant_id: str
    ticket_id: str
    resolution: str
    outcome: str  # e.g. "resolved", "escalated", "refunded"
    embedding: list[float]
    created_at: datetime
    expires_at: datetime | None
    superseded_by: str | None = None  # id of the newer memory that replaces this


class Episodic:
    """Resolution memory store.

    retrieve() returns non-expired, non-superseded memories for the given
    tenant only, ranked by cosine similarity to the query embedding.
    consolidate() clusters similar memories and returns short known-issue notes.
    """

    _CONSOLIDATE_THRESHOLD: float = 0.85  # cosine similarity to group as same issue

    def __init__(self) -> None:
        self._memories: dict[str, EpisodicMemory] = {}  # id → memory

    def write(
        self,
        *,
        tenant_id: str,
        ticket_id: str,
        resolution: str,
        outcome: str,
        embedding: list[float],
        expires_at: datetime | None = None,
    ) -> EpisodicMemory:
        mem = EpisodicMemory(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            ticket_id=ticket_id,
            resolution=resolution,
            outcome=outcome,
            embedding=embedding,
            created_at=datetime.now(UTC),
            expires_at=expires_at,
        )
        self._memories[mem.id] = mem
        return mem

    def supersede(self, old_id: str, new_id: str) -> None:
        """Mark old_id as superseded by new_id."""
        if old_id in self._memories:
            self._memories[old_id].superseded_by = new_id

    def retrieve(
        self,
        *,
        tenant_id: str,
        query_embedding: list[float],
        top_k: int = 5,
        as_of: datetime | None = None,
    ) -> list[EpisodicMemory]:
        """Return top-k memories for tenant, excluding expired and superseded ones."""
        now = as_of or datetime.now(UTC)
        candidates = [
            m
            for m in self._memories.values()
            if m.tenant_id == tenant_id
            and m.superseded_by is None
            and (m.expires_at is None or m.expires_at > now)
        ]
        ranked = sorted(
            candidates,
            key=lambda m: _cosine(m.embedding, query_embedding),
            reverse=True,
        )
        return ranked[:top_k]

    def consolidate(self) -> list[str]:
        """Cluster non-expired, non-superseded memories by similarity.

        Returns one known-issue note per cluster (groups of ≥2 similar memories).
        """
        now = datetime.now(UTC)
        active = [
            m
            for m in self._memories.values()
            if m.superseded_by is None and (m.expires_at is None or m.expires_at > now)
        ]

        assigned: set[str] = set()
        notes: list[str] = []

        for i, anchor in enumerate(active):
            if anchor.id in assigned:
                continue
            cluster = [anchor]
            for other in active[i + 1 :]:
                if other.id in assigned:
                    continue
                if _cosine(anchor.embedding, other.embedding) >= self._CONSOLIDATE_THRESHOLD:
                    cluster.append(other)
                    assigned.add(other.id)
            assigned.add(anchor.id)

            if len(cluster) >= 2:
                tenants = {m.tenant_id for m in cluster}
                outcomes = {m.outcome for m in cluster}
                notes.append(
                    f"Known issue ({len(cluster)} cases, tenants={sorted(tenants)}, "
                    f"outcomes={sorted(outcomes)}): {anchor.resolution[:120]}"
                )

        return notes
