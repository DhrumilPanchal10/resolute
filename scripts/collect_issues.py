#!/usr/bin/env python3
"""Collect closed GitHub issues that have a maintainer resolution.

Outputs JSONL to evals/data/real_issues/issues.jsonl.
Each row: id, repo, title, body, created_at, closed_at,
          resolution_text, resolution_url, labels.

Usage:
    python scripts/collect_issues.py           # uses DEFAULT_REPOS
    python scripts/collect_issues.py --repos tiangolo/fastapi,pydantic/pydantic
    python scripts/collect_issues.py --limit 300

Requires GITHUB_TOKEN in .env (or env var).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx
from pydantic import BaseModel, field_validator

ROOT = Path(__file__).parent.parent

DEFAULT_REPOS: list[str] = [
    "tiangolo/fastapi",
    "pydantic/pydantic",
    "langchain-ai/langchain",
]
OUTPUT_PATH = ROOT / "evals" / "data" / "real_issues" / "issues.jsonl"
PER_PAGE = 100  # GitHub max


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class IssueRow(BaseModel):
    id: str
    repo: str
    title: str
    body: str
    created_at: str
    closed_at: str
    resolution_text: str
    resolution_url: str
    labels: list[str]

    @field_validator("id", "repo", "title", "created_at", "closed_at")
    @classmethod
    def non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("field must not be empty")
        return v


# ---------------------------------------------------------------------------
# GitHub helpers
# ---------------------------------------------------------------------------


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


async def _get_resolution(
    client: httpx.AsyncClient,
    token: str,
    owner: str,
    repo: str,
    number: int,
    maintainers: set[str],
) -> tuple[str, str] | None:
    """Return (resolution_text, resolution_url) from the first maintainer comment, or None."""
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{number}/comments"
    params: dict[str, str | int] = {"per_page": 100}
    resp = await client.get(url, headers=_headers(token), params=params)
    resp.raise_for_status()
    for comment in resp.json():
        login = comment.get("user", {}).get("login", "")
        if login in maintainers:
            return comment["body"], comment["html_url"]
    return None


async def collect_repo(
    client: httpx.AsyncClient,
    token: str,
    repo: str,
    limit: int,
    maintainers: set[str],
) -> list[IssueRow]:
    owner, name = repo.split("/")
    rows: list[IssueRow] = []
    page = 1
    while len(rows) < limit:
        url = f"https://api.github.com/repos/{owner}/{name}/issues"
        params: dict[str, str | int] = {
            "state": "closed",
            "per_page": PER_PAGE,
            "page": page,
        }
        resp = await client.get(url, headers=_headers(token), params=params)
        resp.raise_for_status()
        issues = resp.json()
        if not issues:
            break
        for issue in issues:
            if len(rows) >= limit:
                break
            # skip PRs returned by the issues endpoint
            if "pull_request" in issue:
                continue
            resolution = await _get_resolution(
                client, token, owner, name, issue["number"], maintainers
            )
            if resolution is None:
                continue
            resolution_text, resolution_url = resolution
            rows.append(
                IssueRow(
                    id=f"{repo}#{issue['number']}",
                    repo=repo,
                    title=issue["title"] or "",
                    body=issue.get("body") or "",
                    created_at=issue["created_at"],
                    closed_at=issue["closed_at"] or issue["created_at"],
                    resolution_text=resolution_text,
                    resolution_url=resolution_url,
                    labels=[lbl["name"] for lbl in issue.get("labels", [])],
                )
            )
            print(f"  [{repo}] collected #{issue['number']} ({len(rows)}/{limit})")
        page += 1
    return rows


async def _get_maintainers(
    client: httpx.AsyncClient, token: str, owner: str, name: str
) -> set[str]:
    """Return logins of users with write/maintain/admin access."""
    url = f"https://api.github.com/repos/{owner}/{name}/contributors"
    resp = await client.get(
        url, headers=_headers(token), params={"per_page": 30}
    )
    if resp.status_code != 200:
        return set()
    return {c["login"] for c in resp.json() if isinstance(c, dict)}


async def run(repos: list[str], limit: int) -> None:
    from dotenv import load_dotenv
    import os

    load_dotenv(ROOT / ".env")
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        sys.exit("GITHUB_TOKEN is not set — add it to .env")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    all_rows: list[IssueRow] = []
    per_repo = max(1, limit // len(repos))

    async with httpx.AsyncClient(timeout=30) as client:
        for repo in repos:
            owner, name = repo.split("/")
            print(f"Fetching maintainers for {repo}…")
            maintainers = await _get_maintainers(client, token, owner, name)
            print(f"Collecting issues from {repo}…")
            rows = await collect_repo(client, token, repo, per_repo, maintainers)
            all_rows.extend(rows)
            print(f"  → {len(rows)} issues collected from {repo}")

    with OUTPUT_PATH.open("w") as fh:
        for row in all_rows:
            fh.write(row.model_dump_json() + "\n")

    print(f"\nTotal: {len(all_rows)} issues → {OUTPUT_PATH}")
    if len(all_rows) < 100:
        sys.exit(f"ERROR: only {len(all_rows)} rows collected (need ≥100)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repos",
        default=",".join(DEFAULT_REPOS),
        help="Comma-separated owner/repo list",
    )
    parser.add_argument("--limit", type=int, default=100, help="Total issues to collect")
    args = parser.parse_args()
    repos = [r.strip() for r in args.repos.split(",") if r.strip()]
    asyncio.run(run(repos, args.limit))


if __name__ == "__main__":
    main()
