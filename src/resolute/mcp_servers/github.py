"""GitHub MCP server — search_issues, get_issue, search_code, create_issue.

Architecture
------------
GitHubClient wraps the GitHub REST API v3 via httpx.  Each instance holds the
requesting user's personal access token; there is no shared admin token.

The public tools are:

  search_issues(q, tenant_id, user_roles, as_of, github_token)
      Full-text issue search.  `as_of` appends `created:<=YYYY-MM-DD` to q.
      Requires github.read.

  get_issue(issue_number, repo, tenant_id, user_roles, github_token)
      Fetch a single issue by number.  Returns None if not found (404).
      Requires github.read.

  search_code(q, tenant_id, user_roles, github_token)
      Code search across the configured repo.  Requires github.read.

  create_issue(title, body, labels, repo, tenant_id, user_roles, github_token)
      Create a new issue.  Requires github.write.

For offline / unit tests inject a FakeGitHubClient via the tool factories.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Protocol

import httpx

from agentcore.audit import AuditLog
from resolute.mcp_servers.base import ToolRisk, mcp_tool

# ---------------------------------------------------------------------------
# Gateway Protocol
# ---------------------------------------------------------------------------


class GitHubGateway(Protocol):
    """Duck-type interface satisfied by both GitHubClient and FakeGitHubClient."""

    async def search_issues(self, q: str, as_of: str | None = None) -> list[dict[str, Any]]: ...

    async def get_issue(self, issue_number: int, repo: str) -> dict[str, Any] | None: ...

    async def search_code(self, q: str) -> list[dict[str, Any]]: ...

    async def create_issue(
        self,
        title: str,
        body: str,
        repo: str,
        labels: list[str] | None = None,
    ) -> dict[str, Any]: ...


# ---------------------------------------------------------------------------
# Real GitHub REST client
# ---------------------------------------------------------------------------


@dataclass
class GitHubClient:
    """Thin async wrapper around the GitHub REST API v3.

    Args:
        token:    GitHub personal access token (PAT) for the calling user.
        default_repo: Default owner/repo used when `repo` is omitted in calls.
        base_url: Override for GitHub Enterprise or test servers.
    """

    token: str
    default_repo: str = ""
    base_url: str = "https://api.github.com"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def search_issues(self, q: str, as_of: str | None = None) -> list[dict[str, Any]]:
        full_q = q
        if as_of:
            try:
                cutoff = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
                date_str = cutoff.astimezone(UTC).strftime("%Y-%m-%d")
                full_q = f"{q} created:<={date_str}"
            except ValueError:
                pass
        async with httpx.AsyncClient(headers=self._headers(), timeout=10) as client:
            resp = await client.get(
                f"{self.base_url}/search/issues",
                params={"q": full_q, "per_page": 20, "sort": "updated"},
            )
            resp.raise_for_status()
            data = resp.json()
        return [_normalise_issue(item) for item in data.get("items", [])]

    async def get_issue(self, issue_number: int, repo: str = "") -> dict[str, Any] | None:
        target = repo or self.default_repo
        async with httpx.AsyncClient(headers=self._headers(), timeout=10) as client:
            resp = await client.get(f"{self.base_url}/repos/{target}/issues/{issue_number}")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
        return _normalise_issue(resp.json())

    async def search_code(self, q: str) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(headers=self._headers(), timeout=10) as client:
            resp = await client.get(
                f"{self.base_url}/search/code",
                params={"q": q, "per_page": 10},
            )
            resp.raise_for_status()
            data = resp.json()
        return [_normalise_code(item) for item in data.get("items", [])]

    async def create_issue(
        self,
        title: str,
        body: str,
        repo: str = "",
        labels: list[str] | None = None,
    ) -> dict[str, Any]:
        target = repo or self.default_repo
        payload: dict[str, Any] = {"title": title, "body": body}
        if labels:
            payload["labels"] = labels
        async with httpx.AsyncClient(headers=self._headers(), timeout=10) as client:
            resp = await client.post(f"{self.base_url}/repos/{target}/issues", json=payload)
            resp.raise_for_status()
        return _normalise_issue(resp.json())


def _normalise_issue(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "number": raw.get("number"),
        "title": raw.get("title", ""),
        "body": (raw.get("body") or "")[:2000],
        "state": raw.get("state", ""),
        "created_at": raw.get("created_at", ""),
        "updated_at": raw.get("updated_at", ""),
        "html_url": raw.get("html_url", ""),
        "labels": [lb.get("name", "") for lb in raw.get("labels", [])],
        "user": (raw.get("user") or {}).get("login", ""),
    }


def _normalise_code(raw: dict[str, Any]) -> dict[str, Any]:
    repo = raw.get("repository") or {}
    return {
        "name": raw.get("name", ""),
        "path": raw.get("path", ""),
        "html_url": raw.get("html_url", ""),
        "repo": repo.get("full_name", ""),
        "score": raw.get("score", 0.0),
    }


# ---------------------------------------------------------------------------
# In-memory fake for unit tests
# ---------------------------------------------------------------------------


@dataclass
class FakeGitHubClient:
    """In-memory GitHub gateway for offline unit tests."""

    issues: list[dict[str, Any]] = field(default_factory=list)
    code_results: list[dict[str, Any]] = field(default_factory=list)
    created: list[dict[str, Any]] = field(default_factory=list)

    async def search_issues(self, q: str, as_of: str | None = None) -> list[dict[str, Any]]:
        cutoff: date | None = None
        if as_of:
            with contextlib.suppress(ValueError):
                cutoff = datetime.fromisoformat(as_of.replace("Z", "+00:00")).date()

        results = []
        q_lower = q.lower()
        for issue in self.issues:
            text = (issue.get("title", "") + " " + (issue.get("body") or "")).lower()
            if any(term in text for term in q_lower.split()):
                if cutoff:
                    created = issue.get("created_at", "")
                    try:
                        d = datetime.fromisoformat(created.replace("Z", "+00:00")).date()
                        if d > cutoff:
                            continue
                    except ValueError:
                        pass
                results.append(issue)
        return results

    async def get_issue(self, issue_number: int, repo: str = "") -> dict[str, Any] | None:
        for issue in self.issues:
            if issue.get("number") == issue_number:
                return issue
        return None

    async def search_code(self, q: str) -> list[dict[str, Any]]:
        q_lower = q.lower()
        return [
            r
            for r in self.code_results
            if any(
                term in (r.get("path", "") + r.get("name", "")).lower() for term in q_lower.split()
            )
        ]

    async def create_issue(
        self,
        title: str,
        body: str,
        repo: str = "",
        labels: list[str] | None = None,
    ) -> dict[str, Any]:
        issue: dict[str, Any] = {
            "number": len(self.issues) + len(self.created) + 1,
            "title": title,
            "body": body,
            "state": "open",
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
            "html_url": f"https://github.com/{repo}/issues/{len(self.created) + 1}",
            "labels": labels or [],
            "user": "test-user",
        }
        self.created.append(issue)
        return issue


# ---------------------------------------------------------------------------
# Tool factories
# ---------------------------------------------------------------------------


def make_search_issues_tool(
    client: GitHubGateway,
    audit_log: AuditLog | None = None,
    span_sink: list[Any] | None = None,
) -> Any:
    @mcp_tool(
        "github",
        "read",
        risk=ToolRisk.READ,
        audit_log=audit_log,
        span_sink=span_sink,
    )
    async def search_issues(
        q: str,
        tenant_id: str,
        user_roles: list[str],
        as_of: str | None = None,
        github_token: str = "",
    ) -> list[dict[str, Any]]:
        return await client.search_issues(q, as_of)

    return search_issues


def make_get_issue_tool(
    client: GitHubGateway,
    audit_log: AuditLog | None = None,
    span_sink: list[Any] | None = None,
) -> Any:
    @mcp_tool(
        "github",
        "read",
        risk=ToolRisk.READ,
        audit_log=audit_log,
        span_sink=span_sink,
    )
    async def get_issue(
        issue_number: int,
        tenant_id: str,
        user_roles: list[str],
        repo: str = "",
        github_token: str = "",
    ) -> dict[str, Any] | None:
        return await client.get_issue(issue_number, repo)

    return get_issue


def make_search_code_tool(
    client: GitHubGateway,
    audit_log: AuditLog | None = None,
    span_sink: list[Any] | None = None,
) -> Any:
    @mcp_tool(
        "github",
        "read",
        risk=ToolRisk.READ,
        audit_log=audit_log,
        span_sink=span_sink,
    )
    async def search_code(
        q: str,
        tenant_id: str,
        user_roles: list[str],
        github_token: str = "",
    ) -> list[dict[str, Any]]:
        return await client.search_code(q)

    return search_code


def make_create_issue_tool(
    client: GitHubGateway,
    audit_log: AuditLog | None = None,
    span_sink: list[Any] | None = None,
) -> Any:
    @mcp_tool(
        "github",
        "write",
        risk=ToolRisk.WRITE,
        audit_log=audit_log,
        span_sink=span_sink,
    )
    async def create_issue(
        title: str,
        body: str,
        tenant_id: str,
        user_roles: list[str],
        repo: str = "",
        labels: list[str] | None = None,
        github_token: str = "",
    ) -> dict[str, Any]:
        return await client.create_issue(title, body, repo, labels)

    return create_issue


# ---------------------------------------------------------------------------
# MCPServer registration
# ---------------------------------------------------------------------------


def create_github_server(
    client: GitHubGateway,
    audit_log: AuditLog | None = None,
) -> Any:
    """Return a configured MCPServer for all four GitHub tools."""
    from mcp.server.mcpserver import MCPServer

    server = MCPServer("resolute-github")
    search_issues_fn = make_search_issues_tool(client, audit_log=audit_log)
    get_issue_fn = make_get_issue_tool(client, audit_log=audit_log)
    search_code_fn = make_search_code_tool(client, audit_log=audit_log)
    create_issue_fn = make_create_issue_tool(client, audit_log=audit_log)

    @server.tool()
    async def search_issues(
        q: str,
        tenant_id: str,
        user_roles: list[str],
        as_of: str | None = None,
        github_token: str = "",
        token: str = "",
    ) -> list[dict[str, Any]]:
        """Search GitHub issues with optional time-travel cutoff."""
        result: list[dict[str, Any]] = await search_issues_fn(
            token=token,
            q=q,
            tenant_id=tenant_id,
            user_roles=user_roles,
            as_of=as_of,
            github_token=github_token,
        )
        return result

    @server.tool()
    async def get_issue(
        issue_number: int,
        tenant_id: str,
        user_roles: list[str],
        repo: str = "",
        github_token: str = "",
        token: str = "",
    ) -> dict[str, Any] | None:
        """Fetch a single GitHub issue by number."""
        result: dict[str, Any] | None = await get_issue_fn(
            token=token,
            issue_number=issue_number,
            tenant_id=tenant_id,
            user_roles=user_roles,
            repo=repo,
            github_token=github_token,
        )
        return result

    @server.tool()
    async def search_code(
        q: str,
        tenant_id: str,
        user_roles: list[str],
        github_token: str = "",
        token: str = "",
    ) -> list[dict[str, Any]]:
        """Search code across the configured repository."""
        result: list[dict[str, Any]] = await search_code_fn(
            token=token,
            q=q,
            tenant_id=tenant_id,
            user_roles=user_roles,
            github_token=github_token,
        )
        return result

    @server.tool()
    async def create_issue(
        title: str,
        body: str,
        tenant_id: str,
        user_roles: list[str],
        repo: str = "",
        labels: list[str] | None = None,
        github_token: str = "",
        token: str = "",
    ) -> dict[str, Any]:
        """Create a new GitHub issue."""
        result: dict[str, Any] = await create_issue_fn(
            token=token,
            title=title,
            body=body,
            tenant_id=tenant_id,
            user_roles=user_roles,
            repo=repo,
            labels=labels,
            github_token=github_token,
        )
        return result

    return server
