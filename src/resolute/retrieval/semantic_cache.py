"""Semantic cache for documentation-answerable replies.

Key: tenant_id + permission_scope + docs_version + query embedding
Lookup: cosine similarity against cached embeddings; hit if above threshold.

The cache is in-memory (dict-based) with optional Redis backing.
In production, the embedding vectors would be stored in a vector DB.
For simplicity and offline testing, we use a dict + cosine similarity scan.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CacheEntry:
    query: str
    embedding: list[float]
    response: str
    tenant_id: str
    permission_scope: str
    docs_version: str
    created_at: float = field(default_factory=time.monotonic)
    ttl_seconds: float = 3600.0
    hits: int = 0

    @property
    def expired(self) -> bool:
        return (time.monotonic() - self.created_at) > self.ttl_seconds


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _scope_key(tenant_id: str, permission_scope: str, docs_version: str) -> str:
    return f"{tenant_id}:{permission_scope}:{docs_version}"


@dataclass
class SemanticCache:
    """In-memory semantic cache with cosine similarity lookup.

    Args:
        similarity_threshold: Minimum cosine similarity for a cache hit (0-1).
        ttl_seconds: Default TTL for cache entries.
        max_entries_per_scope: Maximum cached entries per tenant+scope+version.
        embed_fn: Optional function to embed a query string. If None,
                  callers must provide pre-computed embeddings.
    """

    similarity_threshold: float = 0.92
    ttl_seconds: float = 3600.0
    max_entries_per_scope: int = 1000
    embed_fn: Any = None  # Callable[[str], list[float]] | None

    _entries: dict[str, list[CacheEntry]] = field(default_factory=dict)
    _stats: dict[str, int] = field(default_factory=lambda: {"hits": 0, "misses": 0, "evictions": 0})

    def _embed(self, query: str) -> list[float]:
        if self.embed_fn is not None:
            return self.embed_fn(query)
        raise ValueError("No embed_fn configured; provide embedding directly")

    def lookup(
        self,
        *,
        query: str | None = None,
        embedding: list[float] | None = None,
        tenant_id: str,
        permission_scope: str,
        docs_version: str,
    ) -> str | None:
        """Look up a cached response by semantic similarity.

        Returns the cached response if a similar query exists, else None.
        """
        if embedding is None:
            if query is None:
                raise ValueError("Provide query or embedding")
            embedding = self._embed(query)

        key = _scope_key(tenant_id, permission_scope, docs_version)
        entries = self._entries.get(key, [])

        best_sim = 0.0
        best_entry: CacheEntry | None = None

        for entry in entries:
            if entry.expired:
                continue
            sim = _cosine_similarity(embedding, entry.embedding)
            if sim > best_sim:
                best_sim = sim
                best_entry = entry

        if best_entry is not None and best_sim >= self.similarity_threshold:
            best_entry.hits += 1
            self._stats["hits"] += 1
            return best_entry.response

        self._stats["misses"] += 1
        return None

    def store(
        self,
        *,
        query: str,
        embedding: list[float] | None = None,
        response: str,
        tenant_id: str,
        permission_scope: str,
        docs_version: str,
        ttl_seconds: float | None = None,
    ) -> None:
        """Cache a response with its query embedding."""
        if embedding is None:
            embedding = self._embed(query)

        key = _scope_key(tenant_id, permission_scope, docs_version)
        if key not in self._entries:
            self._entries[key] = []

        entries = self._entries[key]

        # Evict expired entries
        before = len(entries)
        entries[:] = [e for e in entries if not e.expired]
        self._stats["evictions"] += before - len(entries)

        # Evict oldest if at capacity
        if len(entries) >= self.max_entries_per_scope:
            entries.sort(key=lambda e: e.created_at)
            removed = len(entries) - self.max_entries_per_scope + 1
            entries[:] = entries[removed:]
            self._stats["evictions"] += removed

        entries.append(CacheEntry(
            query=query,
            embedding=embedding,
            response=response,
            tenant_id=tenant_id,
            permission_scope=permission_scope,
            docs_version=docs_version,
            ttl_seconds=ttl_seconds or self.ttl_seconds,
        ))

    def invalidate(
        self,
        *,
        tenant_id: str | None = None,
        docs_version: str | None = None,
    ) -> int:
        """Invalidate entries by tenant and/or docs_version. Returns count removed."""
        removed = 0
        keys_to_delete: list[str] = []

        for key, entries in self._entries.items():
            parts = key.split(":")
            scope_tenant = parts[0] if parts else ""
            scope_version = parts[2] if len(parts) > 2 else ""

            if tenant_id and scope_tenant != tenant_id:
                continue
            if docs_version and scope_version != docs_version:
                continue

            removed += len(entries)
            keys_to_delete.append(key)

        for k in keys_to_delete:
            del self._entries[k]

        return removed

    @property
    def stats(self) -> dict[str, Any]:
        total = self._stats["hits"] + self._stats["misses"]
        return {
            "hits": self._stats["hits"],
            "misses": self._stats["misses"],
            "hit_rate": self._stats["hits"] / total if total > 0 else 0.0,
            "evictions": self._stats["evictions"],
            "total_entries": sum(len(v) for v in self._entries.values()),
        }

    def clear(self) -> None:
        self._entries.clear()
        self._stats = {"hits": 0, "misses": 0, "evictions": 0}
