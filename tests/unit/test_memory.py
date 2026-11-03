"""Tests for agentcore.memory — source enforcement, TTL, tenant isolation."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from agentcore.memory import (
    ALLOWED_LONG_TERM_SOURCES,
    Episodic,
    LongTerm,
    MemorySourceError,
    ShortTerm,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _vec(val: float, dim: int = 4) -> list[float]:
    """Vector for similarity tests: val in first dim, (1-val) in second.
    Higher val → more aligned with query [1,0,0,0] → higher cosine similarity."""
    v = [0.0] * dim
    v[0] = val
    v[1] = 1.0 - val
    return v


def _future(days: int = 1) -> datetime:
    return datetime.now(UTC) + timedelta(days=days)


def _past(days: int = 1) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


# ---------------------------------------------------------------------------
# ShortTerm
# ---------------------------------------------------------------------------


class TestShortTerm:
    def test_add_and_retrieve(self) -> None:
        st = ShortTerm()
        st.add({"role": "user", "content": "hello"})
        assert len(st.messages()) == 1

    async def test_no_compact_under_limit(self) -> None:
        st = ShortTerm()
        st.add({"role": "user", "content": "hi"})

        called = False

        async def summarise(msgs: list[dict[str, Any]]) -> str:
            nonlocal called
            called = True
            return "summary"

        compacted = await st.maybe_compact(summarise)
        assert not compacted
        assert not called

    async def test_compact_over_limit(self) -> None:
        st = ShortTerm()
        # Fill beyond MAX_TOKENS (each ~250 tokens → 9 messages = 2250 > 2000)
        for i in range(9):
            st.add({"role": "user", "content": "x" * 1000})

        async def summarise(msgs: list[dict[str, Any]]) -> str:
            return f"summary of {len(msgs)} messages"

        compacted = await st.maybe_compact(summarise)
        assert compacted
        # Tail kept verbatim + one summary message
        msgs = st.messages()
        assert msgs[0]["content"].startswith("summary of")
        assert len(msgs) == ShortTerm.TAIL_KEEP + 1

    async def test_compact_idempotent_after_compaction(self) -> None:
        st = ShortTerm()
        for _ in range(8):
            st.add({"role": "user", "content": "x" * 1000})

        async def summarise(msgs: list[dict[str, Any]]) -> str:
            return "summary"

        await st.maybe_compact(summarise)
        # Second call should not compact again (now well under limit)
        compacted2 = await st.maybe_compact(summarise)
        assert not compacted2


# ---------------------------------------------------------------------------
# LongTerm — source enforcement
# ---------------------------------------------------------------------------


class TestLongTerm:
    def test_allowed_sources_accepted(self) -> None:
        lt = LongTerm()
        for source in ALLOWED_LONG_TERM_SOURCES:
            lt.write(
                tenant_id="t", customer_id="c", key="plan", value="enterprise", source=source
            )

    @pytest.mark.parametrize("bad_source", ["customer_text", "llm_inference", "unknown", ""])
    def test_untrusted_source_rejected(self, bad_source: str) -> None:
        lt = LongTerm()
        with pytest.raises(MemorySourceError):
            lt.write(
                tenant_id="t", customer_id="c", key="plan", value="x", source=bad_source
            )

    def test_get_returns_written_facts(self) -> None:
        lt = LongTerm()
        lt.write(
            tenant_id="t", customer_id="c", key="tier", value="pro", source="system_data"
        )
        facts = lt.get(tenant_id="t", customer_id="c")
        assert facts["tier"].value == "pro"

    def test_cross_tenant_isolation(self) -> None:
        lt = LongTerm()
        lt.write(
            tenant_id="tenant-a", customer_id="c1", key="x", value="secret", source="system_data"
        )
        # tenant-b sees nothing for the same customer id
        assert lt.get(tenant_id="tenant-b", customer_id="c1") == {}

    def test_missing_customer_returns_empty(self) -> None:
        assert LongTerm().get(tenant_id="t", customer_id="nobody") == {}


# ---------------------------------------------------------------------------
# Episodic — TTL, supersession, cross-tenant
# ---------------------------------------------------------------------------


class TestEpisodic:
    def _write(
        self,
        ep: Episodic,
        tenant: str = "tenant-a",
        vec: float = 1.0,
        expires_at: datetime | None = None,
    ) -> Any:
        return ep.write(
            tenant_id=tenant,
            ticket_id="tkt-1",
            resolution="solution text",
            outcome="resolved",
            embedding=_vec(vec),
            expires_at=expires_at,
        )

    # Expiry
    def test_expired_memory_not_returned(self) -> None:
        ep = Episodic()
        self._write(ep, expires_at=_past())  # expired
        self._write(ep, vec=0.5, expires_at=_future())  # valid
        results = ep.retrieve(tenant_id="tenant-a", query_embedding=_vec(1.0))
        assert len(results) == 1
        assert results[0].expires_at is not None and results[0].expires_at > datetime.now(UTC)

    def test_non_expiring_memory_always_returned(self) -> None:
        ep = Episodic()
        self._write(ep, expires_at=None)
        results = ep.retrieve(tenant_id="tenant-a", query_embedding=_vec(1.0))
        assert len(results) == 1

    # Supersession
    def test_superseded_memory_not_returned(self) -> None:
        ep = Episodic()
        old = self._write(ep, vec=1.0)
        new = self._write(ep, vec=0.9)
        ep.supersede(old.id, new.id)
        results = ep.retrieve(tenant_id="tenant-a", query_embedding=_vec(1.0))
        # Only new memory returned
        assert all(r.id != old.id for r in results)
        assert any(r.id == new.id for r in results)

    # Cross-tenant isolation
    def test_cross_tenant_never_returned(self) -> None:
        ep = Episodic()
        self._write(ep, tenant="tenant-a")
        self._write(ep, tenant="tenant-b", vec=0.5)
        results_a = ep.retrieve(tenant_id="tenant-a", query_embedding=_vec(1.0))
        assert all(r.tenant_id == "tenant-a" for r in results_a)
        results_b = ep.retrieve(tenant_id="tenant-b", query_embedding=_vec(1.0))
        assert all(r.tenant_id == "tenant-b" for r in results_b)

    # Similarity ranking
    def test_top_k_ordered_by_similarity(self) -> None:
        ep = Episodic()
        # vec(1.0) is most similar to query vec(1.0); vec(0.1) is least
        for v in [0.1, 0.5, 1.0]:
            self._write(ep, vec=v)
        results = ep.retrieve(tenant_id="tenant-a", query_embedding=_vec(1.0), top_k=3)
        assert results[0].embedding[0] == pytest.approx(1.0)

    def test_top_k_respected(self) -> None:
        ep = Episodic()
        for v in [0.1, 0.3, 0.6, 0.9, 1.0]:
            self._write(ep)
        results = ep.retrieve(tenant_id="tenant-a", query_embedding=_vec(1.0), top_k=2)
        assert len(results) == 2


# ---------------------------------------------------------------------------
# Episodic.consolidate
# ---------------------------------------------------------------------------


class TestConsolidate:
    def test_similar_memories_produce_note(self) -> None:
        ep = Episodic()
        # Two nearly identical embeddings → same cluster
        for _ in range(2):
            ep.write(
                tenant_id="t",
                ticket_id="tkt",
                resolution="SSL cert expired on ingress",
                outcome="resolved",
                embedding=[1.0, 0.0, 0.0],
            )
        notes = ep.consolidate()
        assert len(notes) >= 1
        assert "SSL cert expired" in notes[0]

    def test_dissimilar_memories_no_note(self) -> None:
        ep = Episodic()
        ep.write(
            tenant_id="t", ticket_id="a", resolution="SSL issue", outcome="resolved",
            embedding=[1.0, 0.0, 0.0],
        )
        ep.write(
            tenant_id="t", ticket_id="b", resolution="billing query", outcome="resolved",
            embedding=[0.0, 1.0, 0.0],
        )
        notes = ep.consolidate()
        assert notes == []

    def test_expired_excluded_from_consolidate(self) -> None:
        ep = Episodic()
        # One expired, one valid — not enough for a cluster
        ep.write(
            tenant_id="t", ticket_id="a", resolution="same issue", outcome="resolved",
            embedding=[1.0, 0.0, 0.0], expires_at=_past(),
        )
        ep.write(
            tenant_id="t", ticket_id="b", resolution="same issue", outcome="resolved",
            embedding=[1.0, 0.0, 0.0], expires_at=_future(),
        )
        notes = ep.consolidate()
        assert notes == []
