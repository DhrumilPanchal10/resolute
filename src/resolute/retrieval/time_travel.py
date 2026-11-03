"""Time-travel helpers — thin wrappers over acl.AccessContext."""

from __future__ import annotations

from datetime import UTC, datetime

from resolute.retrieval.acl import AccessContext


def context_at(
    *,
    tenant_id: str,
    user_roles: frozenset[str] | set[str] | list[str],
    as_of: str | datetime | None = None,
) -> AccessContext:
    """Build an AccessContext, parsing as_of from ISO string if needed."""
    roles = frozenset(user_roles) if not isinstance(user_roles, frozenset) else user_roles
    if isinstance(as_of, str):
        as_of = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    if isinstance(as_of, datetime) and as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=UTC)
    return AccessContext(tenant_id=tenant_id, user_roles=roles, as_of=as_of)
