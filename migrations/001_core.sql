-- Migration 001: core schema with per-tenant RLS
-- Run as the superuser (resolute) who owns the database.
-- app_user is a restricted role used by the application; it cannot bypass RLS.

-- ---------------------------------------------------------------------------
-- Roles
-- ---------------------------------------------------------------------------

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
        CREATE ROLE app_user NOLOGIN;
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- Extensions
-- ---------------------------------------------------------------------------

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgvector";

-- ---------------------------------------------------------------------------
-- tenants  (no RLS — the root table)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS tenants (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name        TEXT NOT NULL,
    plan        TEXT NOT NULL DEFAULT 'free',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- users
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS users (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    external_id TEXT NOT NULL,          -- Clerk user_id
    email       TEXT NOT NULL,
    role        TEXT NOT NULL DEFAULT 'support_engineer',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, external_id)
);

ALTER TABLE users ENABLE ROW LEVEL SECURITY;

CREATE POLICY users_tenant_isolation ON users
    USING (tenant_id = current_setting('app.tenant_id', TRUE)::UUID);

GRANT SELECT, INSERT, UPDATE ON users TO app_user;

-- ---------------------------------------------------------------------------
-- accounts  (customers of a tenant)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS accounts (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    email       TEXT NOT NULL,
    plan        TEXT NOT NULL DEFAULT 'starter',
    mrr_usd     NUMERIC(10, 2) NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE accounts ENABLE ROW LEVEL SECURITY;

CREATE POLICY accounts_tenant_isolation ON accounts
    USING (tenant_id = current_setting('app.tenant_id', TRUE)::UUID);

GRANT SELECT, INSERT, UPDATE ON accounts TO app_user;

-- ---------------------------------------------------------------------------
-- invoices
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS invoices (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    account_id      UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    amount_usd      NUMERIC(10, 2) NOT NULL,
    status          TEXT NOT NULL DEFAULT 'open',  -- open | paid | void | refunded
    stripe_id       TEXT,
    issued_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    due_at          TIMESTAMPTZ,
    paid_at         TIMESTAMPTZ
);

ALTER TABLE invoices ENABLE ROW LEVEL SECURITY;

CREATE POLICY invoices_tenant_isolation ON invoices
    USING (tenant_id = current_setting('app.tenant_id', TRUE)::UUID);

GRANT SELECT, INSERT, UPDATE ON invoices TO app_user;

-- ---------------------------------------------------------------------------
-- tickets
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS tickets (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    account_id      UUID REFERENCES accounts(id),
    external_id     TEXT,                           -- e.g. Intercom/Zendesk id
    title           TEXT NOT NULL,
    body            TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'open',   -- open | in_progress | resolved | escalated
    category        TEXT,
    severity        TEXT,
    tier            TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at     TIMESTAMPTZ
);

ALTER TABLE tickets ENABLE ROW LEVEL SECURITY;

CREATE POLICY tickets_tenant_isolation ON tickets
    USING (tenant_id = current_setting('app.tenant_id', TRUE)::UUID);

GRANT SELECT, INSERT, UPDATE ON tickets TO app_user;

-- ---------------------------------------------------------------------------
-- messages  (conversation thread on a ticket)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS messages (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    ticket_id   UUID NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    role        TEXT NOT NULL,  -- customer | agent | system
    content     TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE messages ENABLE ROW LEVEL SECURITY;

CREATE POLICY messages_tenant_isolation ON messages
    USING (tenant_id = current_setting('app.tenant_id', TRUE)::UUID);

GRANT SELECT, INSERT ON messages TO app_user;

-- ---------------------------------------------------------------------------
-- audit_events  (append-only; RLS read-only for app_user)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS audit_events (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    event_type  TEXT NOT NULL,
    actor_id    TEXT NOT NULL,
    payload     JSONB NOT NULL DEFAULT '{}',
    prev_hash   TEXT NOT NULL DEFAULT '',
    hash        TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY;

CREATE POLICY audit_events_tenant_isolation ON audit_events
    USING (tenant_id = current_setting('app.tenant_id', TRUE)::UUID);

-- app_user can insert but NOT delete/update (append-only)
GRANT SELECT, INSERT ON audit_events TO app_user;

-- ---------------------------------------------------------------------------
-- memories  (long-term per-customer facts)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS memories (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    customer_id     TEXT NOT NULL,
    source          TEXT NOT NULL,   -- system_data | verified_outcome
    content         TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ,
    superseded_by   UUID REFERENCES memories(id)
);

ALTER TABLE memories ENABLE ROW LEVEL SECURITY;

CREATE POLICY memories_tenant_isolation ON memories
    USING (tenant_id = current_setting('app.tenant_id', TRUE)::UUID);

GRANT SELECT, INSERT, UPDATE ON memories TO app_user;

-- ---------------------------------------------------------------------------
-- approvals  (HITL gate records)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS approvals (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    ticket_id       UUID NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    action_type     TEXT NOT NULL,
    payload         JSONB NOT NULL DEFAULT '{}',
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending | approved | rejected | edited
    reviewer_id     TEXT,
    reviewed_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE approvals ENABLE ROW LEVEL SECURITY;

CREATE POLICY approvals_tenant_isolation ON approvals
    USING (tenant_id = current_setting('app.tenant_id', TRUE)::UUID);

GRANT SELECT, INSERT, UPDATE ON approvals TO app_user;

-- ---------------------------------------------------------------------------
-- doc_chunks  (pgvector — Phase 3)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS doc_chunks (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    doc_id          TEXT NOT NULL,
    chunk_index     INT NOT NULL,
    heading_path    TEXT NOT NULL DEFAULT '',
    text            TEXT NOT NULL,
    embedding       VECTOR(384),
    acl_roles       TEXT[] NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    docs_version    TEXT NOT NULL DEFAULT ''
);

ALTER TABLE doc_chunks ENABLE ROW LEVEL SECURITY;

CREATE POLICY doc_chunks_tenant_isolation ON doc_chunks
    USING (tenant_id = current_setting('app.tenant_id', TRUE)::UUID);

GRANT SELECT, INSERT, UPDATE, DELETE ON doc_chunks TO app_user;

-- HNSW index for approximate nearest-neighbour search
CREATE INDEX IF NOT EXISTS doc_chunks_embedding_hnsw
    ON doc_chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- ---------------------------------------------------------------------------
-- Helper: set_tenant(uuid) — convenience wrapper
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION set_tenant(p_tenant_id UUID)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM set_config('app.tenant_id', p_tenant_id::TEXT, TRUE);
END;
$$;

GRANT EXECUTE ON FUNCTION set_tenant(UUID) TO app_user;
