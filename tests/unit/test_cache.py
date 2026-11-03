"""Tests for agentcore.cache — key isolation and get_or_set behaviour."""

import pytest
import fakeredis.aioredis as fakeredis

from agentcore.cache import build_key, get_or_set


# ---------------------------------------------------------------------------
# Key builder
# ---------------------------------------------------------------------------


class TestBuildKey:
    def _key(self, **overrides: str) -> str:
        base = dict(
            tenant_id="tenant-a",
            permission_scope="support_engineer",
            docs_version="v3",
            namespace="search",
        )
        base.update(overrides)
        return build_key(**base)  # type: ignore[arg-type]

    def test_different_tenant_different_key(self) -> None:
        assert self._key(tenant_id="tenant-a") != self._key(tenant_id="tenant-b")

    def test_different_permission_scope_different_key(self) -> None:
        assert self._key(permission_scope="support_engineer") != self._key(
            permission_scope="admin"
        )

    def test_different_docs_version_different_key(self) -> None:
        assert self._key(docs_version="v1") != self._key(docs_version="v2")

    def test_same_inputs_same_key(self) -> None:
        assert self._key() == self._key()

    def test_key_contains_all_required_dimensions(self) -> None:
        key = self._key()
        assert "tenant-a" in key
        assert "support_engineer" in key
        assert "v3" in key

    def test_params_affect_key(self) -> None:
        k1 = build_key(
            tenant_id="t", permission_scope="s", docs_version="v1",
            namespace="n", params={"q": "hello"},
        )
        k2 = build_key(
            tenant_id="t", permission_scope="s", docs_version="v1",
            namespace="n", params={"q": "world"},
        )
        assert k1 != k2


# ---------------------------------------------------------------------------
# get_or_set
# ---------------------------------------------------------------------------


class TestGetOrSet:
    @pytest.fixture()
    def redis(self) -> fakeredis.FakeRedis:
        return fakeredis.FakeRedis()

    async def test_cache_miss_calls_fn_and_stores(self, redis: fakeredis.FakeRedis) -> None:
        calls = 0

        async def fn() -> str:
            nonlocal calls
            calls += 1
            return "result-1"

        key = build_key(
            tenant_id="t", permission_scope="s", docs_version="v1", namespace="n"
        )
        val = await get_or_set(redis, key, ttl=60, fn=fn)
        assert val == "result-1"
        assert calls == 1

    async def test_cache_hit_skips_fn(self, redis: fakeredis.FakeRedis) -> None:
        calls = 0

        async def fn() -> str:
            nonlocal calls
            calls += 1
            return "fresh"

        key = build_key(
            tenant_id="t", permission_scope="s", docs_version="v1", namespace="n"
        )
        await get_or_set(redis, key, ttl=60, fn=fn)
        result = await get_or_set(redis, key, ttl=60, fn=fn)
        assert result == "fresh"
        assert calls == 1  # fn called only once

    async def test_different_scopes_independent(self, redis: fakeredis.FakeRedis) -> None:
        async def fn_a() -> str:
            return "scope-a"

        async def fn_b() -> str:
            return "scope-b"

        key_a = build_key(
            tenant_id="t", permission_scope="admin", docs_version="v1", namespace="n"
        )
        key_b = build_key(
            tenant_id="t", permission_scope="support_engineer", docs_version="v1", namespace="n"
        )
        val_a = await get_or_set(redis, key_a, ttl=60, fn=fn_a)
        val_b = await get_or_set(redis, key_b, ttl=60, fn=fn_b)
        assert val_a == "scope-a"
        assert val_b == "scope-b"
