"""Integration test: RLS tenant isolation (T2.3).

Requires a live Postgres with pgvector.  Run with:
    make up && uv run pytest tests/integration/test_rls.py -v

Skipped automatically when the database is unreachable or OFFLINE=1.
"""

from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Skip guard
# ---------------------------------------------------------------------------


def _db_available() -> bool:
    if os.environ.get("OFFLINE") or os.environ.get("CI"):
        return False
    try:
        import socket

        host, port = "localhost", 5432
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


skip_if_no_db = pytest.mark.skipif(
    not _db_available(),
    reason="Postgres not reachable; run 'make up' first",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def migrated_engine():
    """Apply migration (idempotent IF NOT EXISTS) and return the engine."""
    from pathlib import Path

    from resolute.db import engine, run_migration

    sql = (Path(__file__).parent.parent.parent / "migrations" / "001_core.sql").read_text()
    await run_migration(sql)
    yield engine
    # Clean up test-prefixed tenants
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM tenants WHERE name LIKE 'rls_test_%'"))


@pytest_asyncio.fixture
async def two_tenants(migrated_engine):
    """Insert two tenants and return (tenant_a_id, tenant_b_id)."""
    from resolute.db import engine

    tid_a = uuid.uuid4()
    tid_b = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO tenants (id, name) VALUES (:id, :name)"),
            [
                {"id": str(tid_a), "name": "rls_test_a"},
                {"id": str(tid_b), "name": "rls_test_b"},
            ],
        )
    yield tid_a, tid_b
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM tenants WHERE id IN (:a, :b)"),
            {"a": str(tid_a), "b": str(tid_b)},
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@skip_if_no_db
async def test_tenant_a_cannot_read_tenant_b_tickets(two_tenants):
    """Core RLS assertion: tenant A session sees zero rows from tenant B."""
    from resolute.db import db_session

    tid_a, tid_b = two_tenants

    # Insert a ticket for tenant B using the engine owner (bypasses RLS)
    from resolute.db import engine

    ticket_id = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO tickets (id, tenant_id, title, body) "
                "VALUES (:id, :tid, 'secret', 'body')"
            ),
            {"id": str(ticket_id), "tid": str(tid_b)},
        )

    # Tenant A session should see no tickets
    async with db_session(tenant_id=tid_a) as sess:
        result = await sess.execute(text("SELECT id FROM tickets"))
        rows = result.fetchall()
        ids = [str(r[0]) for r in rows]
        assert str(ticket_id) not in ids, "Tenant A must not see tenant B tickets"

    # Tenant B session should see its own ticket
    async with db_session(tenant_id=tid_b) as sess:
        result = await sess.execute(
            text("SELECT id FROM tickets WHERE id = :id"),
            {"id": str(ticket_id)},
        )
        assert result.fetchone() is not None, "Tenant B must see its own ticket"

    # Cleanup
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM tickets WHERE id = :id"), {"id": str(ticket_id)})


@skip_if_no_db
async def test_rls_applies_to_all_tenant_tables(two_tenants):
    """Check RLS on accounts, invoices, messages, audit_events, approvals, memories."""
    from resolute.db import db_session, engine

    tid_a, tid_b = two_tenants

    # Seed rows for tenant B in every table (using owner connection, no RLS)
    acc_id = uuid.uuid4()
    ticket_id = uuid.uuid4()

    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO accounts (id, tenant_id, name, email) VALUES (:id, :tid, 'acme', 'x@acme.com')"
            ),
            {"id": str(acc_id), "tid": str(tid_b)},
        )
        await conn.execute(
            text("INSERT INTO tickets (id, tenant_id, title, body) VALUES (:id, :tid, 't', 'b')"),
            {"id": str(ticket_id), "tid": str(tid_b)},
        )
        await conn.execute(
            text(
                "INSERT INTO invoices (id, tenant_id, account_id, amount_usd) VALUES (:id, :tid, :aid, 99)"
            ),
            {"id": str(uuid.uuid4()), "tid": str(tid_b), "aid": str(acc_id)},
        )
        await conn.execute(
            text(
                "INSERT INTO messages (id, tenant_id, ticket_id, role, content) VALUES (:id, :tid, :tkid, 'agent', 'hi')"
            ),
            {"id": str(uuid.uuid4()), "tid": str(tid_b), "tkid": str(ticket_id)},
        )
        await conn.execute(
            text(
                "INSERT INTO audit_events (id, tenant_id, event_type, actor_id, hash) "
                "VALUES (:id, :tid, 'test', 'sys', 'abc')"
            ),
            {"id": str(uuid.uuid4()), "tid": str(tid_b)},
        )
        await conn.execute(
            text(
                "INSERT INTO memories (id, tenant_id, customer_id, source, content) "
                "VALUES (:id, :tid, 'cust1', 'system_data', 'fact')"
            ),
            {"id": str(uuid.uuid4()), "tid": str(tid_b)},
        )
        await conn.execute(
            text(
                "INSERT INTO approvals (id, tenant_id, ticket_id, action_type) "
                "VALUES (:id, :tid, :tkid, 'refund')"
            ),
            {"id": str(uuid.uuid4()), "tid": str(tid_b), "tkid": str(ticket_id)},
        )

    # Tenant A must see nothing in any of these tables
    tables = ["accounts", "invoices", "messages", "audit_events", "memories", "approvals"]
    async with db_session(tenant_id=tid_a) as sess:
        for table in tables:
            result = await sess.execute(text(f"SELECT COUNT(*) FROM {table}"))  # noqa: S608
            count = result.scalar()
            assert count == 0, f"Tenant A leaked into {table} (got {count} rows)"

    # Cleanup
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM approvals WHERE tenant_id = :tid"), {"tid": str(tid_b)}
        )
        await conn.execute(text("DELETE FROM memories WHERE tenant_id = :tid"), {"tid": str(tid_b)})
        await conn.execute(
            text("DELETE FROM audit_events WHERE tenant_id = :tid"), {"tid": str(tid_b)}
        )
        await conn.execute(text("DELETE FROM messages WHERE tenant_id = :tid"), {"tid": str(tid_b)})
        await conn.execute(text("DELETE FROM invoices WHERE tenant_id = :tid"), {"tid": str(tid_b)})
        await conn.execute(text("DELETE FROM tickets WHERE id = :id"), {"id": str(ticket_id)})
        await conn.execute(text("DELETE FROM accounts WHERE id = :id"), {"id": str(acc_id)})


@skip_if_no_db
async def test_set_tenant_function_sets_config(migrated_engine):
    """set_tenant(uuid) convenience function should set app.tenant_id."""
    from resolute.db import engine

    test_id = uuid.uuid4()
    async with engine.connect() as conn:
        await conn.execute(text("SELECT set_tenant(:id)"), {"id": str(test_id)})
        result = await conn.execute(text("SELECT current_setting('app.tenant_id', TRUE)"))
        value = result.scalar()
        assert value == str(test_id)
