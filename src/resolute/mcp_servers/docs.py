"""Docs MCP server — search_docs(query, k) over the Phase-3 retrieval stack.

Architecture
------------
DocsStore wraps a BM25Index + flat doc list.  At startup the store is built
from pre-embedded doc dicts (populated by the ingest pipeline or the eval
harness).

The public MCP tool is registered via `create_docs_server(store)`, which
returns an `MCPServer` with a single `search_docs` tool guarded by the base
wrapper (JWT, RBAC, circuit breaker, audit, span).

For unit tests the tool function is also exported directly as
`search_docs_tool` so tests can call it without spinning up an HTTP process.

Embedding
---------
`DocsStore.embed_fn` defaults to the real `embed_texts` (loads BAAI model on
first call).  Tests inject a lightweight stub by passing `embed_fn=...` to
`DocsStore`, keeping tests fast and offline.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from agentcore.audit import AuditLog
from resolute.mcp_servers.base import ToolRisk, mcp_tool
from resolute.retrieval.acl import AccessContext
from resolute.retrieval.hybrid import BM25Index, hybrid_search
from resolute.retrieval.time_travel import context_at

# ---------------------------------------------------------------------------
# DocsStore
# ---------------------------------------------------------------------------


@dataclass
class DocsStore:
    """Holds the doc corpus and a lazy BM25 index.

    Args:
        docs:       List of doc dicts with keys: doc_id, tenant_id, acl_roles,
                    created_at, docs_version, text, embedding (list[float]).
        embed_fn:   Function (texts: list[str]) -> list[list[float]].
                    Defaults to the real embed_texts; override in tests.
    """

    docs: list[dict[str, Any]] = field(default_factory=list)
    embed_fn: Callable[[list[str]], list[list[float]]] | None = None

    _bm25: BM25Index | None = field(default=None, init=False, repr=False)

    def _get_embed_fn(self) -> Callable[[list[str]], list[list[float]]]:
        if self.embed_fn is not None:
            return self.embed_fn
        from resolute.retrieval.embed import embed_texts

        return embed_texts

    def rebuild_index(self) -> None:
        idx = BM25Index()
        idx.build(self.docs)
        self._bm25 = idx

    @property
    def bm25(self) -> BM25Index:
        if self._bm25 is None:
            self.rebuild_index()
        return self._bm25

    def embed_query(self, query: str) -> list[float]:
        return self._get_embed_fn()([query])[0]


# ---------------------------------------------------------------------------
# Tool factory
# ---------------------------------------------------------------------------


def make_search_docs_tool(
    store: DocsStore,
    audit_log: AuditLog | None = None,
    span_sink: list | None = None,
) -> Callable:
    """Return a guarded search_docs coroutine bound to the given DocsStore.

    The returned callable has the standard `mcp_tool` guard applied:
      JWT verify → RBAC (docs.read) → circuit breaker → audit → timeout → span.

    Parameters passed to the tool:
        query:      Search query string.
        tenant_id:  Caller's tenant (extracted from JWT org_id in production;
                    passed explicitly here for testability).
        user_roles: Caller's roles (from JWT; passed explicitly in tests).
        k:          Number of results to return (default 5).
        as_of:      ISO timestamp for time-travel; None = current corpus.
        rerank:     Whether to run cross-encoder reranking (default True;
                    skipped when OFFLINE=1 or model unavailable).
    """

    @mcp_tool(
        "docs",
        "read",
        risk=ToolRisk.READ,
        audit_log=audit_log,
        span_sink=span_sink,
    )
    async def search_docs(
        query: str,
        tenant_id: str,
        user_roles: list[str],
        k: int = 5,
        as_of: str | None = None,
        rerank: bool = True,
    ) -> list[dict[str, Any]]:
        ctx: AccessContext = context_at(
            tenant_id=tenant_id,
            user_roles=frozenset(user_roles),
            as_of=as_of,
        )
        q_emb = store.embed_query(query)
        candidates = hybrid_search(query, q_emb, store.docs, store.bm25, ctx, top_k=30)

        if rerank and candidates and not os.environ.get("OFFLINE"):
            try:
                from resolute.retrieval.rerank import rerank as _rerank

                ranked = _rerank(query, candidates, top_n=k)
            except Exception:
                ranked = candidates[:k]
        else:
            ranked = candidates[:k]

        return [
            {
                "doc_id": doc.get("doc_id", ""),
                "heading_path": doc.get("heading_path", ""),
                "text": doc.get("text", "")[:500],  # truncate for MCP payload
                "score": round(score, 4),
            }
            for doc, score in ranked
        ]

    return search_docs


# ---------------------------------------------------------------------------
# MCPServer registration (lazy — avoids importing mcp unless needed)
# ---------------------------------------------------------------------------


def create_docs_server(
    store: DocsStore,
    audit_log: AuditLog | None = None,
) -> Any:
    """Return a configured MCPServer for the docs tool.

    Deferred import of mcp so unit tests that don't need the server don't
    pay the import cost.
    """
    from mcp.server.mcpserver import MCPServer

    server = MCPServer("resolute-docs")
    tool_fn = make_search_docs_tool(store, audit_log=audit_log)

    @server.tool()
    async def search_docs(  # type: ignore[no-untyped-def]
        query: str,
        tenant_id: str,
        user_roles: list[str],
        k: int = 5,
        as_of: str | None = None,
        rerank: bool = True,
        token: str = "",
    ) -> list[dict[str, Any]]:
        """Search the documentation corpus using hybrid BM25 + dense retrieval."""
        return await tool_fn(
            token=token,
            query=query,
            tenant_id=tenant_id,
            user_roles=user_roles,
            k=k,
            as_of=as_of,
            rerank=rerank,
        )

    return server
