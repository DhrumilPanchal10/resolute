"""Offline unit tests for mcp_servers/docs.py (T4.2).

Uses locally-signed RSA JWTs and a fake embed_fn — no ML models, no network.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

# ---------------------------------------------------------------------------
# RSA key pair
# ---------------------------------------------------------------------------

_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PUBLIC_KEY = _PRIVATE_KEY.public_key()
_KID = "docs-test-kid"


def _jwks_dict() -> dict[str, Any]:
    import json

    from jwt.algorithms import RSAAlgorithm

    jwk_dict = json.loads(RSAAlgorithm.to_jwk(_PUBLIC_KEY))
    jwk_dict["kid"] = _KID
    return {"keys": [jwk_dict]}


def _make_token(
    *,
    sub: str = "user_1",
    org_id: str = "tenant_1",
    role: str = "support_engineer",
    exp_offset: int = 3600,
) -> str:
    payload: dict[str, Any] = {
        "sub": sub,
        "org_id": org_id,
        "role": role,
        "iat": int(time.time()),
        "exp": int(time.time()) + exp_offset,
    }
    priv_pem = _PRIVATE_KEY.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )
    return jwt.encode(payload, priv_pem, algorithm="RS256", headers={"kid": _KID})


@pytest.fixture(autouse=True)
def inject_jwks():
    from agentcore.auth import _set_test_jwks

    _set_test_jwks(_jwks_dict())
    yield
    _set_test_jwks(None)


# ---------------------------------------------------------------------------
# Fake embed function: maps text to a 4-dim vector based on keyword presence
# ---------------------------------------------------------------------------


def _fake_embed(texts: list[str]) -> list[list[float]]:
    """Deterministic fake embeddings — no ML models loaded."""
    keywords = ["authentication", "billing", "deployment", "logging"]
    result = []
    for text in texts:
        low = text.lower()
        vec = [1.0 if kw in low else 0.0 for kw in keywords]
        # Normalise
        norm = sum(x * x for x in vec) ** 0.5 or 1.0
        result.append([x / norm for x in vec])
    return result


# ---------------------------------------------------------------------------
# Shared corpus fixture
# ---------------------------------------------------------------------------


def _make_store(tenant_id: str = "tenant_1") -> object:
    from resolute.mcp_servers.docs import DocsStore

    docs = [
        {
            "doc_id": "doc_auth",
            "tenant_id": tenant_id,
            "acl_roles": [],
            "created_at": "2020-01-01T00:00:00Z",
            "docs_version": "v1",
            "heading_path": "Authentication",
            "text": "Authentication using OAuth and JWT tokens for secure API access.",
            "embedding": _fake_embed(["Authentication using OAuth and JWT tokens"])[0],
        },
        {
            "doc_id": "doc_billing",
            "tenant_id": tenant_id,
            "acl_roles": [],
            "created_at": "2020-01-01T00:00:00Z",
            "docs_version": "v1",
            "heading_path": "Billing",
            "text": "Billing and invoice management for subscription plans.",
            "embedding": _fake_embed(["Billing and invoice management"])[0],
        },
        {
            "doc_id": "doc_deploy",
            "tenant_id": tenant_id,
            "acl_roles": [],
            "created_at": "2020-01-01T00:00:00Z",
            "docs_version": "v1",
            "heading_path": "Deployment",
            "text": "Deployment guide for Docker and Kubernetes environments.",
            "embedding": _fake_embed(["Deployment guide for Docker"])[0],
        },
        {
            "doc_id": "doc_admin_only",
            "tenant_id": tenant_id,
            "acl_roles": ["admin"],  # restricted
            "created_at": "2020-01-01T00:00:00Z",
            "docs_version": "v1",
            "heading_path": "Admin > Secrets",
            "text": "Internal admin secrets and configuration.",
            "embedding": _fake_embed(["admin secrets configuration"])[0],
        },
        {
            "doc_id": "doc_future",
            "tenant_id": tenant_id,
            "acl_roles": [],
            "created_at": "2030-01-01T00:00:00Z",  # future doc
            "docs_version": "v2",
            "heading_path": "Future Feature",
            "text": "Authentication improvements planned for 2030.",
            "embedding": _fake_embed(["Authentication improvements 2030"])[0],
        },
        {
            "doc_id": "doc_other_tenant",
            "tenant_id": "other_tenant",
            "acl_roles": [],
            "created_at": "2020-01-01T00:00:00Z",
            "docs_version": "v1",
            "heading_path": "Other",
            "text": "Authentication guide for other tenant.",
            "embedding": _fake_embed(["Authentication guide"])[0],
        },
    ]
    return DocsStore(docs=docs, embed_fn=_fake_embed)


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------


class TestSearchDocs:
    @pytest.mark.asyncio
    async def test_returns_results(self) -> None:
        from resolute.mcp_servers.docs import make_search_docs_tool

        store = _make_store()
        tool = make_search_docs_tool(store)
        token = _make_token(role="support_engineer")

        results = await tool(
            token=token,
            query="authentication JWT",
            tenant_id="tenant_1",
            user_roles=["support_engineer"],
            k=3,
            rerank=False,
        )
        assert len(results) > 0
        doc_ids = [r["doc_id"] for r in results]
        assert "doc_auth" in doc_ids

    @pytest.mark.asyncio
    async def test_k_limits_results(self) -> None:
        from resolute.mcp_servers.docs import make_search_docs_tool

        store = _make_store()
        tool = make_search_docs_tool(store)
        token = _make_token()

        results = await tool(
            token=token,
            query="guide",
            tenant_id="tenant_1",
            user_roles=["support_engineer"],
            k=2,
            rerank=False,
        )
        assert len(results) <= 2

    @pytest.mark.asyncio
    async def test_result_has_expected_keys(self) -> None:
        from resolute.mcp_servers.docs import make_search_docs_tool

        store = _make_store()
        tool = make_search_docs_tool(store)
        token = _make_token()

        results = await tool(
            token=token,
            query="billing",
            tenant_id="tenant_1",
            user_roles=["support_engineer"],
            k=1,
            rerank=False,
        )
        assert len(results) >= 1
        r = results[0]
        assert {"doc_id", "heading_path", "text", "score"} <= r.keys()

    @pytest.mark.asyncio
    async def test_audit_events_written(self) -> None:
        from agentcore.audit import AuditLog
        from resolute.mcp_servers.docs import make_search_docs_tool

        log = AuditLog()
        store = _make_store()
        tool = make_search_docs_tool(store, audit_log=log)
        token = _make_token()

        await tool(
            token=token,
            query="deployment",
            tenant_id="tenant_1",
            user_roles=["support_engineer"],
            k=2,
            rerank=False,
        )
        types = [e.event_type for e in log.entries()]
        assert "tool_call_start" in types
        assert "tool_call_success" in types

    @pytest.mark.asyncio
    async def test_span_emitted(self) -> None:
        from resolute.mcp_servers.docs import make_search_docs_tool

        spans: list = []
        store = _make_store()
        tool = make_search_docs_tool(store, span_sink=spans)
        token = _make_token()

        await tool(
            token=token,
            query="deployment",
            tenant_id="tenant_1",
            user_roles=["support_engineer"],
            k=2,
            rerank=False,
        )
        assert len(spans) == 1
        assert spans[0].success is True


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


class TestDocsACL:
    @pytest.mark.asyncio
    async def test_admin_only_doc_hidden_from_support(self) -> None:
        from resolute.mcp_servers.docs import make_search_docs_tool

        store = _make_store()
        tool = make_search_docs_tool(store)
        token = _make_token(role="support_engineer")

        results = await tool(
            token=token,
            query="admin secrets",
            tenant_id="tenant_1",
            user_roles=["support_engineer"],
            k=5,
            rerank=False,
        )
        doc_ids = [r["doc_id"] for r in results]
        assert "doc_admin_only" not in doc_ids

    @pytest.mark.asyncio
    async def test_admin_sees_admin_only_doc(self) -> None:
        from resolute.mcp_servers.docs import make_search_docs_tool

        store = _make_store()
        tool = make_search_docs_tool(store)
        token = _make_token(role="admin")

        results = await tool(
            token=token,
            query="admin secrets configuration",
            tenant_id="tenant_1",
            user_roles=["admin"],
            k=5,
            rerank=False,
        )
        doc_ids = [r["doc_id"] for r in results]
        assert "doc_admin_only" in doc_ids

    @pytest.mark.asyncio
    async def test_cross_tenant_doc_never_returned(self) -> None:
        from resolute.mcp_servers.docs import make_search_docs_tool

        store = _make_store()
        tool = make_search_docs_tool(store)
        token = _make_token(role="support_engineer")

        results = await tool(
            token=token,
            query="authentication guide other tenant",
            tenant_id="tenant_1",
            user_roles=["support_engineer"],
            k=10,
            rerank=False,
        )
        doc_ids = [r["doc_id"] for r in results]
        assert "doc_other_tenant" not in doc_ids

    @pytest.mark.asyncio
    async def test_time_travel_excludes_future_doc(self) -> None:
        from resolute.mcp_servers.docs import make_search_docs_tool

        store = _make_store()
        tool = make_search_docs_tool(store)
        token = _make_token()

        results = await tool(
            token=token,
            query="authentication improvements",
            tenant_id="tenant_1",
            user_roles=["support_engineer"],
            k=10,
            as_of="2025-01-01T00:00:00Z",
            rerank=False,
        )
        doc_ids = [r["doc_id"] for r in results]
        assert "doc_future" not in doc_ids


# ---------------------------------------------------------------------------
# RBAC denial
# ---------------------------------------------------------------------------


class TestDocsRBAC:
    @pytest.mark.asyncio
    async def test_missing_token_raises(self) -> None:
        from resolute.mcp_servers.base import ToolPermissionError
        from resolute.mcp_servers.docs import make_search_docs_tool

        store = _make_store()
        tool = make_search_docs_tool(store)

        with pytest.raises(ToolPermissionError, match="missing"):
            await tool(
                token="",
                query="auth",
                tenant_id="tenant_1",
                user_roles=["support_engineer"],
            )

    @pytest.mark.asyncio
    async def test_expired_token_raises(self) -> None:
        from resolute.mcp_servers.base import ToolPermissionError
        from resolute.mcp_servers.docs import make_search_docs_tool

        store = _make_store()
        tool = make_search_docs_tool(store)
        token = _make_token(exp_offset=-10)

        with pytest.raises(ToolPermissionError, match="expired"):
            await tool(
                token=token,
                query="auth",
                tenant_id="tenant_1",
                user_roles=["support_engineer"],
            )
