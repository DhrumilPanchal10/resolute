"""ACL and time-travel filter helpers.

Used by both BM25 and pgvector query paths so access-control logic lives in
one place and cannot diverge.

A document is visible to a request when ALL of the following hold:
  1. doc.tenant_id == request.tenant_id
  2. any(r in doc.acl_roles for r in request.user_roles)  — empty acl means public
  3. doc.created_at < as_of  (time-travel; None means "now", i.e. no filter)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class AccessContext:
    tenant_id: str
    user_roles: frozenset[str]
    as_of: datetime | None = None  # None = current time (no past-view)


def is_visible(
    *,
    doc_tenant_id: str,
    doc_acl_roles: list[str],
    doc_created_at: datetime | str,
    ctx: AccessContext,
) -> bool:
    """Return True if the document is visible under ctx."""
    # 1. Tenant isolation
    if doc_tenant_id != ctx.tenant_id:
        return False

    # 2. ACL (empty acl_roles means document is public within tenant)
    if doc_acl_roles and not any(r in ctx.user_roles for r in doc_acl_roles):
        return False

    # 3. Time-travel
    if ctx.as_of is not None:
        if isinstance(doc_created_at, str):
            doc_dt = datetime.fromisoformat(doc_created_at.replace("Z", "+00:00"))
        else:
            doc_dt = doc_created_at
        if doc_dt.tzinfo is None:
            doc_dt = doc_dt.replace(tzinfo=UTC)
        as_of = ctx.as_of
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=UTC)
        if doc_dt >= as_of:
            return False

    return True


def filter_docs(
    docs: list[dict],
    ctx: AccessContext,
    *,
    tenant_key: str = "tenant_id",
    acl_key: str = "acl_roles",
    created_key: str = "created_at",
) -> list[dict]:
    """Filter a list of doc dicts using is_visible."""
    visible = []
    for doc in docs:
        if is_visible(
            doc_tenant_id=doc.get(tenant_key, ""),
            doc_acl_roles=doc.get(acl_key, []),
            doc_created_at=doc.get(created_key, "2000-01-01T00:00:00Z"),
            ctx=ctx,
        ):
            visible.append(doc)
    return visible
