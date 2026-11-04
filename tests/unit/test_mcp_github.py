"""Offline unit tests for mcp_servers/github.py (T4.4).

Uses locally-signed RSA JWTs and FakeGitHubClient — no GitHub API, no network.
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
_KID = "github-test-kid"


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
# Shared fake client fixture
# ---------------------------------------------------------------------------


def _make_client() -> object:
    from resolute.mcp_servers.github import FakeGitHubClient

    return FakeGitHubClient(
        issues=[
            {
                "number": 1,
                "title": "Authentication fails on login",
                "body": "Users see 401 when using OAuth tokens after the recent deploy.",
                "state": "open",
                "created_at": "2023-06-01T00:00:00Z",
                "updated_at": "2023-06-02T00:00:00Z",
                "html_url": "https://github.com/acme/app/issues/1",
                "labels": ["bug", "auth"],
                "user": "alice",
            },
            {
                "number": 2,
                "title": "Billing invoice not generated",
                "body": "Pro plan upgrades do not trigger an invoice.",
                "state": "closed",
                "created_at": "2024-01-10T00:00:00Z",
                "updated_at": "2024-01-15T00:00:00Z",
                "html_url": "https://github.com/acme/app/issues/2",
                "labels": ["billing"],
                "user": "bob",
            },
            {
                "number": 3,
                "title": "Future issue in 2030",
                "body": "This issue is from the future.",
                "state": "open",
                "created_at": "2030-01-01T00:00:00Z",
                "updated_at": "2030-01-01T00:00:00Z",
                "html_url": "https://github.com/acme/app/issues/3",
                "labels": [],
                "user": "charlie",
            },
        ],
        code_results=[
            {
                "name": "auth.py",
                "path": "src/auth.py",
                "html_url": "https://github.com/acme/app/blob/main/src/auth.py",
                "repo": "acme/app",
                "score": 0.9,
            },
            {
                "name": "billing.py",
                "path": "src/billing.py",
                "html_url": "https://github.com/acme/app/blob/main/src/billing.py",
                "repo": "acme/app",
                "score": 0.7,
            },
        ],
    )


# ---------------------------------------------------------------------------
# search_issues tests
# ---------------------------------------------------------------------------


class TestSearchIssues:
    @pytest.mark.asyncio
    async def test_returns_matching_issues(self) -> None:
        from resolute.mcp_servers.github import make_search_issues_tool

        client = _make_client()
        tool = make_search_issues_tool(client)
        token = _make_token()

        results = await tool(
            token=token,
            q="authentication",
            tenant_id="tenant_1",
            user_roles=["support_engineer"],
        )
        assert len(results) >= 1
        assert any(r["number"] == 1 for r in results)

    @pytest.mark.asyncio
    async def test_as_of_excludes_future_issues(self) -> None:
        from resolute.mcp_servers.github import make_search_issues_tool

        client = _make_client()
        tool = make_search_issues_tool(client)
        token = _make_token()

        results = await tool(
            token=token,
            q="future",
            tenant_id="tenant_1",
            user_roles=["support_engineer"],
            as_of="2025-01-01T00:00:00Z",
        )
        assert not any(r["number"] == 3 for r in results)

    @pytest.mark.asyncio
    async def test_as_of_includes_older_issues(self) -> None:
        from resolute.mcp_servers.github import make_search_issues_tool

        client = _make_client()
        tool = make_search_issues_tool(client)
        token = _make_token()

        results = await tool(
            token=token,
            q="authentication",
            tenant_id="tenant_1",
            user_roles=["support_engineer"],
            as_of="2025-01-01T00:00:00Z",
        )
        assert any(r["number"] == 1 for r in results)

    @pytest.mark.asyncio
    async def test_result_has_expected_keys(self) -> None:
        from resolute.mcp_servers.github import make_search_issues_tool

        client = _make_client()
        tool = make_search_issues_tool(client)
        token = _make_token()

        results = await tool(
            token=token,
            q="billing",
            tenant_id="tenant_1",
            user_roles=["support_engineer"],
        )
        assert len(results) >= 1
        assert {"number", "title", "body", "state", "html_url", "labels"} <= results[0].keys()

    @pytest.mark.asyncio
    async def test_missing_token_raises(self) -> None:
        from resolute.mcp_servers.base import ToolPermissionError
        from resolute.mcp_servers.github import make_search_issues_tool

        client = _make_client()
        tool = make_search_issues_tool(client)

        with pytest.raises(ToolPermissionError, match="missing"):
            await tool(
                token="",
                q="auth",
                tenant_id="tenant_1",
                user_roles=["support_engineer"],
            )

    @pytest.mark.asyncio
    async def test_audit_events_written(self) -> None:
        from agentcore.audit import AuditLog
        from resolute.mcp_servers.github import make_search_issues_tool

        log = AuditLog()
        client = _make_client()
        tool = make_search_issues_tool(client, audit_log=log)
        token = _make_token()

        await tool(
            token=token,
            q="auth",
            tenant_id="tenant_1",
            user_roles=["support_engineer"],
        )
        types = [e.event_type for e in log.entries()]
        assert "tool_call_start" in types
        assert "tool_call_success" in types


# ---------------------------------------------------------------------------
# get_issue tests
# ---------------------------------------------------------------------------


class TestGetIssue:
    @pytest.mark.asyncio
    async def test_returns_issue_by_number(self) -> None:
        from resolute.mcp_servers.github import make_get_issue_tool

        client = _make_client()
        tool = make_get_issue_tool(client)
        token = _make_token()

        result = await tool(
            token=token,
            issue_number=2,
            tenant_id="tenant_1",
            user_roles=["support_engineer"],
        )
        assert result is not None
        assert result["number"] == 2
        assert "billing" in result["title"].lower()

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_issue(self) -> None:
        from resolute.mcp_servers.github import make_get_issue_tool

        client = _make_client()
        tool = make_get_issue_tool(client)
        token = _make_token()

        result = await tool(
            token=token,
            issue_number=9999,
            tenant_id="tenant_1",
            user_roles=["support_engineer"],
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_span_emitted(self) -> None:
        from resolute.mcp_servers.github import make_get_issue_tool

        spans: list = []
        client = _make_client()
        tool = make_get_issue_tool(client, span_sink=spans)
        token = _make_token()

        await tool(
            token=token,
            issue_number=1,
            tenant_id="tenant_1",
            user_roles=["support_engineer"],
        )
        assert len(spans) == 1
        assert spans[0].success is True


# ---------------------------------------------------------------------------
# search_code tests
# ---------------------------------------------------------------------------


class TestSearchCode:
    @pytest.mark.asyncio
    async def test_returns_code_results(self) -> None:
        from resolute.mcp_servers.github import make_search_code_tool

        client = _make_client()
        tool = make_search_code_tool(client)
        token = _make_token()

        results = await tool(
            token=token,
            q="auth",
            tenant_id="tenant_1",
            user_roles=["support_engineer"],
        )
        assert len(results) >= 1
        assert any("auth" in r["path"] for r in results)

    @pytest.mark.asyncio
    async def test_result_has_expected_keys(self) -> None:
        from resolute.mcp_servers.github import make_search_code_tool

        client = _make_client()
        tool = make_search_code_tool(client)
        token = _make_token()

        results = await tool(
            token=token,
            q="billing",
            tenant_id="tenant_1",
            user_roles=["support_engineer"],
        )
        assert len(results) >= 1
        assert {"name", "path", "html_url", "repo"} <= results[0].keys()

    @pytest.mark.asyncio
    async def test_contractor_can_search_code(self) -> None:
        from resolute.mcp_servers.github import make_search_code_tool

        client = _make_client()
        tool = make_search_code_tool(client)
        token = _make_token(role="contractor")

        results = await tool(
            token=token,
            q="auth",
            tenant_id="tenant_1",
            user_roles=["contractor"],
        )
        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# create_issue tests
# ---------------------------------------------------------------------------


class TestCreateIssue:
    @pytest.mark.asyncio
    async def test_creates_issue(self) -> None:
        from resolute.mcp_servers.github import FakeGitHubClient, make_create_issue_tool

        fake = FakeGitHubClient()
        tool = make_create_issue_tool(fake)
        token = _make_token(role="support_engineer")

        result = await tool(
            token=token,
            title="New bug report",
            body="Something is broken.",
            tenant_id="tenant_1",
            user_roles=["support_engineer"],
            labels=["bug"],
        )
        assert result["title"] == "New bug report"
        assert result["state"] == "open"
        assert len(fake.created) == 1

    @pytest.mark.asyncio
    async def test_contractor_denied_write(self) -> None:
        from resolute.mcp_servers.base import ToolPermissionError
        from resolute.mcp_servers.github import FakeGitHubClient, make_create_issue_tool

        fake = FakeGitHubClient()
        tool = make_create_issue_tool(fake)
        token = _make_token(role="contractor")

        with pytest.raises(ToolPermissionError):
            await tool(
                token=token,
                title="Contractor issue",
                body="Should not be allowed.",
                tenant_id="tenant_1",
                user_roles=["contractor"],
            )

    @pytest.mark.asyncio
    async def test_expired_token_raises(self) -> None:
        from resolute.mcp_servers.base import ToolPermissionError
        from resolute.mcp_servers.github import FakeGitHubClient, make_create_issue_tool

        fake = FakeGitHubClient()
        tool = make_create_issue_tool(fake)
        token = _make_token(exp_offset=-10)

        with pytest.raises(ToolPermissionError, match="expired"):
            await tool(
                token=token,
                title="New bug",
                body="Body.",
                tenant_id="tenant_1",
                user_roles=["support_engineer"],
            )
