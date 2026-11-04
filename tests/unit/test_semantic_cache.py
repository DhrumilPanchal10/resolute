"""Tests for resolute.retrieval.semantic_cache."""
from __future__ import annotations

import time

import pytest

from resolute.retrieval.semantic_cache import (
    CacheEntry,
    SemanticCache,
    _cosine_similarity,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Simple normalized vectors for testing
_VEC_A = [1.0, 0.0, 0.0]
_VEC_B = [0.0, 1.0, 0.0]
_VEC_C = [0.707, 0.707, 0.0]  # 45° between A and B
_VEC_A_NEAR = [0.99, 0.1, 0.0]  # Very close to A


class TestCosineSimilarity:
    def test_identical(self) -> None:
        assert _cosine_similarity(_VEC_A, _VEC_A) == pytest.approx(1.0)

    def test_orthogonal(self) -> None:
        assert _cosine_similarity(_VEC_A, _VEC_B) == pytest.approx(0.0)

    def test_close_vectors(self) -> None:
        sim = _cosine_similarity(_VEC_A, _VEC_A_NEAR)
        assert sim > 0.99

    def test_45_degrees(self) -> None:
        sim = _cosine_similarity(_VEC_A, _VEC_C)
        assert 0.7 < sim < 0.72

    def test_empty_vectors(self) -> None:
        assert _cosine_similarity([], []) == 0.0

    def test_zero_vector(self) -> None:
        assert _cosine_similarity([0, 0, 0], _VEC_A) == 0.0


class TestCacheEntry:
    def test_not_expired(self) -> None:
        e = CacheEntry(
            query="test", embedding=_VEC_A, response="answer",
            tenant_id="t1", permission_scope="s1", docs_version="v1",
            ttl_seconds=3600,
        )
        assert e.expired is False

    def test_expired(self) -> None:
        e = CacheEntry(
            query="test", embedding=_VEC_A, response="answer",
            tenant_id="t1", permission_scope="s1", docs_version="v1",
            created_at=time.monotonic() - 10, ttl_seconds=1,
        )
        assert e.expired is True


class TestSemanticCache:
    def _make_cache(self, threshold: float = 0.9) -> SemanticCache:
        return SemanticCache(similarity_threshold=threshold, ttl_seconds=3600)

    def test_miss_on_empty(self) -> None:
        cache = self._make_cache()
        result = cache.lookup(
            embedding=_VEC_A, tenant_id="t1",
            permission_scope="s1", docs_version="v1",
        )
        assert result is None
        assert cache.stats["misses"] == 1

    def test_exact_hit(self) -> None:
        cache = self._make_cache()
        cache.store(
            query="How do I reset?", embedding=_VEC_A, response="Click reset.",
            tenant_id="t1", permission_scope="s1", docs_version="v1",
        )
        result = cache.lookup(
            embedding=_VEC_A, tenant_id="t1",
            permission_scope="s1", docs_version="v1",
        )
        assert result == "Click reset."
        assert cache.stats["hits"] == 1

    def test_near_hit(self) -> None:
        cache = self._make_cache(threshold=0.95)
        cache.store(
            query="How do I reset?", embedding=_VEC_A, response="Click reset.",
            tenant_id="t1", permission_scope="s1", docs_version="v1",
        )
        result = cache.lookup(
            embedding=_VEC_A_NEAR, tenant_id="t1",
            permission_scope="s1", docs_version="v1",
        )
        assert result == "Click reset."

    def test_miss_below_threshold(self) -> None:
        cache = self._make_cache(threshold=0.95)
        cache.store(
            query="How do I reset?", embedding=_VEC_A, response="Click reset.",
            tenant_id="t1", permission_scope="s1", docs_version="v1",
        )
        result = cache.lookup(
            embedding=_VEC_C, tenant_id="t1",
            permission_scope="s1", docs_version="v1",
        )
        assert result is None

    def test_tenant_isolation(self) -> None:
        cache = self._make_cache()
        cache.store(
            query="q", embedding=_VEC_A, response="Tenant 1 answer",
            tenant_id="t1", permission_scope="s1", docs_version="v1",
        )
        result = cache.lookup(
            embedding=_VEC_A, tenant_id="t2",
            permission_scope="s1", docs_version="v1",
        )
        assert result is None

    def test_docs_version_isolation(self) -> None:
        cache = self._make_cache()
        cache.store(
            query="q", embedding=_VEC_A, response="Old docs answer",
            tenant_id="t1", permission_scope="s1", docs_version="v1",
        )
        result = cache.lookup(
            embedding=_VEC_A, tenant_id="t1",
            permission_scope="s1", docs_version="v2",
        )
        assert result is None

    def test_permission_scope_isolation(self) -> None:
        cache = self._make_cache()
        cache.store(
            query="q", embedding=_VEC_A, response="Admin answer",
            tenant_id="t1", permission_scope="admin", docs_version="v1",
        )
        result = cache.lookup(
            embedding=_VEC_A, tenant_id="t1",
            permission_scope="user", docs_version="v1",
        )
        assert result is None

    def test_expired_entry_missed(self) -> None:
        cache = SemanticCache(similarity_threshold=0.9, ttl_seconds=0.01)
        cache.store(
            query="q", embedding=_VEC_A, response="answer",
            tenant_id="t1", permission_scope="s1", docs_version="v1",
            ttl_seconds=0.01,
        )
        time.sleep(0.02)
        result = cache.lookup(
            embedding=_VEC_A, tenant_id="t1",
            permission_scope="s1", docs_version="v1",
        )
        assert result is None

    def test_invalidate_by_tenant(self) -> None:
        cache = self._make_cache()
        cache.store(
            query="q", embedding=_VEC_A, response="a",
            tenant_id="t1", permission_scope="s1", docs_version="v1",
        )
        cache.store(
            query="q2", embedding=_VEC_B, response="b",
            tenant_id="t2", permission_scope="s1", docs_version="v1",
        )
        removed = cache.invalidate(tenant_id="t1")
        assert removed == 1
        assert cache.lookup(embedding=_VEC_A, tenant_id="t1", permission_scope="s1", docs_version="v1") is None
        assert cache.lookup(embedding=_VEC_B, tenant_id="t2", permission_scope="s1", docs_version="v1") == "b"

    def test_invalidate_by_docs_version(self) -> None:
        cache = self._make_cache()
        cache.store(
            query="q", embedding=_VEC_A, response="old",
            tenant_id="t1", permission_scope="s1", docs_version="v1",
        )
        cache.store(
            query="q2", embedding=_VEC_B, response="new",
            tenant_id="t1", permission_scope="s1", docs_version="v2",
        )
        removed = cache.invalidate(docs_version="v1")
        assert removed == 1

    def test_max_entries_eviction(self) -> None:
        cache = SemanticCache(similarity_threshold=0.9, max_entries_per_scope=2)
        for i in range(3):
            vec = [float(i == j) for j in range(3)]
            cache.store(
                query=f"q{i}", embedding=vec, response=f"a{i}",
                tenant_id="t1", permission_scope="s1", docs_version="v1",
            )
        assert cache.stats["total_entries"] == 2

    def test_hit_rate(self) -> None:
        cache = self._make_cache()
        cache.store(
            query="q", embedding=_VEC_A, response="a",
            tenant_id="t1", permission_scope="s1", docs_version="v1",
        )
        cache.lookup(embedding=_VEC_A, tenant_id="t1", permission_scope="s1", docs_version="v1")
        cache.lookup(embedding=_VEC_A, tenant_id="t1", permission_scope="s1", docs_version="v1")
        cache.lookup(embedding=_VEC_B, tenant_id="t1", permission_scope="s1", docs_version="v1")
        assert cache.stats["hits"] == 2
        assert cache.stats["misses"] == 1
        assert cache.stats["hit_rate"] == pytest.approx(2 / 3)

    def test_clear(self) -> None:
        cache = self._make_cache()
        cache.store(
            query="q", embedding=_VEC_A, response="a",
            tenant_id="t1", permission_scope="s1", docs_version="v1",
        )
        cache.clear()
        assert cache.stats["total_entries"] == 0
        assert cache.stats["hits"] == 0

    def test_embed_fn_integration(self) -> None:
        cache = SemanticCache(
            similarity_threshold=0.9,
            embed_fn=lambda q: _VEC_A,
        )
        cache.store(
            query="How do I reset?", response="Click reset.",
            tenant_id="t1", permission_scope="s1", docs_version="v1",
        )
        result = cache.lookup(
            query="How to do a reset?",
            tenant_id="t1", permission_scope="s1", docs_version="v1",
        )
        assert result == "Click reset."

    def test_no_embed_fn_raises(self) -> None:
        cache = SemanticCache(similarity_threshold=0.9)
        with pytest.raises(ValueError, match="No embed_fn"):
            cache.store(
                query="q", response="a",
                tenant_id="t1", permission_scope="s1", docs_version="v1",
            )
