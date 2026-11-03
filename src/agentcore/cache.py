"""Redis cache helpers.

Key invariant: every cache key MUST include tenant_id, permission_scope, and
docs_version so that one tenant never sees another tenant's data, and stale
docs never surface after a corpus update.
"""

import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import Any

from redis.asyncio import Redis


def build_key(
    *,
    tenant_id: str,
    permission_scope: str,
    docs_version: str,
    namespace: str,
    params: dict[str, Any] | None = None,
) -> str:
    """Build a namespaced cache key that always embeds the three mandatory dimensions.

    Format: resolute:{namespace}:{tenant_id}:{permission_scope}:{docs_version}:{params_hash}
    """
    params_hash = (
        hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()[:12]
        if params
        else "noparams"
    )
    return f"resolute:{namespace}:{tenant_id}:{permission_scope}:{docs_version}:{params_hash}"


async def get_or_set(
    redis: Redis,
    key: str,
    ttl: int,
    fn: Callable[[], Awaitable[str]],
) -> str:
    """Return cached value for key, or call fn(), cache the result, and return it.

    Args:
        redis: Async Redis client.
        key:   Cache key (use build_key to construct it).
        ttl:   Time-to-live in seconds.
        fn:    Async factory called on cache miss; must return a JSON-serialisable str.
    """
    cached = await redis.get(key)
    if cached is not None:
        return cached.decode() if isinstance(cached, bytes) else str(cached)

    value = await fn()
    await redis.set(key, value, ex=ttl)
    return value
