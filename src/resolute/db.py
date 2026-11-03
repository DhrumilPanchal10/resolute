"""Async SQLAlchemy engine + session factory with per-request tenant scoping.

Usage in a FastAPI dependency:

    async with db_session(tenant_id=...) as session:
        result = await session.execute(select(Ticket))

The session executes SET LOCAL app.tenant_id = '<uuid>' before any query,
activating RLS for that transaction.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.sql import text

from resolute.config import settings

# ---------------------------------------------------------------------------
# Engine (singleton per process)
# ---------------------------------------------------------------------------


# psycopg async driver — URL scheme: postgresql+psycopg://
# Strip the sync +psycopg variant and ensure the async scheme.
def _async_url(url: str) -> str:
    if url.startswith("postgresql://") or url.startswith("postgres://"):
        return "postgresql+psycopg://" + url.split("://", 1)[1]
    if url.startswith("postgresql+psycopg://"):
        return url
    # e.g. postgresql+psycopg2:// → replace
    return url.replace("postgresql+psycopg2://", "postgresql+psycopg://")


engine = create_async_engine(
    _async_url(settings.database_url),
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    echo=False,
)

SessionFactory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine,
    expire_on_commit=False,
    autobegin=True,
)

# ---------------------------------------------------------------------------
# Tenant-scoped session context manager
# ---------------------------------------------------------------------------

SYSTEM_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000000")


@asynccontextmanager
async def db_session(
    tenant_id: uuid.UUID | str | None = None,
) -> AsyncGenerator[AsyncSession, None]:
    """Yield an AsyncSession scoped to tenant_id via SET LOCAL app.tenant_id.

    If tenant_id is None the SYSTEM_TENANT_ID sentinel is used (bypasses RLS
    only when RLS is not forced — superuser sessions still bypass it, but
    app_user sessions without a matching row will see nothing).
    """
    tid = str(tenant_id) if tenant_id is not None else str(SYSTEM_TENANT_ID)
    async with SessionFactory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, TRUE)"),
            {"tid": tid},
        )
        yield session


# ---------------------------------------------------------------------------
# Convenience: run the migration SQL file
# ---------------------------------------------------------------------------


async def run_migration(sql: str) -> None:
    """Execute raw migration SQL as the engine owner (bypasses RLS)."""
    async with engine.begin() as conn:
        await conn.execute(text(sql))
